import difflib
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import citations, config, llm, parse, prompts

SEV = {"critical": 0, "major": 1, "minor": 2}
CATS = {"methodology", "statistics", "logic", "claims", "data", "reproducibility", "citations", "ethics", "clarity"}
RECS = {"accept", "minor revision", "major revision", "reject"}
_logger = logging.getLogger(__name__)


def locate(quote, folded, lo=0, hi=None):
    hi = len(folded) if hi is None else hi
    q = parse.fold(str(quote)).strip().strip("\"'.\u2026 ")
    words = q.split()
    if len(words) < 4:
        return None
    seg = folded[lo:hi]
    m = re.search(r"\s+".join(re.escape(w) for w in words), seg, re.I)
    if m:
        return lo + m.start(), lo + m.end()
    sm = difflib.SequenceMatcher(None, seg.lower(), q.lower(), autojunk=False)
    b = sm.find_longest_match(0, len(seg), 0, len(q))
    if b.size >= max(25, 0.7 * len(q)):
        return lo + b.a, lo + b.a + b.size
    return None


def collect(data, folded, lo, hi, label):
    items = data.get("findings") if isinstance(data, dict) else data
    out = []
    for it in (items or [])[:8]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title", "")).strip()
        why = str(it.get("explanation", "")).strip()
        if not title or not why:
            continue
        sev = str(it.get("severity", "")).lower().strip()
        cat = str(it.get("category", "")).lower().strip()
        quote = str(it.get("quote", "")).strip()
        span = locate(quote, folded, lo, hi) or locate(quote, folded)
        out.append({
            "title": title,
            "explanation": why,
            "fix": str(it.get("fix", "")).strip(),
            "severity": sev if sev in SEV else "minor",
            "category": cat if cat in CATS else "logic",
            "quote": quote,
            "span": list(span) if span else None,
            "grounded": span is not None,
            "section": label,
        })
    return out


def overlap(a, b):
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return max(inter, 0) / max(min(a[1] - a[0], b[1] - b[0]), 1)


def dedupe(findings):
    keep = []
    for f in sorted(findings, key=lambda f: (SEV[f["severity"]], not f["grounded"])):
        dup = False
        for k in keep:
            similar = difflib.SequenceMatcher(None, f["title"].lower(), k["title"].lower()).ratio() > 0.8
            same = f["span"] and k["span"] and overlap(f["span"], k["span"]) > 0.5 and f["category"] == k["category"]
            if similar or same:
                dup = True
                break
        if not dup:
            keep.append(f)
    keep.sort(key=lambda f: (not f["grounded"], SEV[f["severity"]], f["span"][0] if f["span"] else 0))
    for i, f in enumerate(keep, 1):
        f["id"] = i
    return keep


def as_list(v):
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def analyze(path, name, online, update):
    text = parse.read_document(path)
    if len(text) < 1200:
        raise ValueError("Not enough text could be extracted. Scanned PDFs need OCR first, which is not included.")
    folded = text.translate(parse.FOLD)
    doc = parse.structure(text, config.CHUNK_CHARS)
    chunks = doc["chunks"]
    n = len(chunks)
    if not n:
        raise ValueError("Could not find any body text to analyse.")

    has_multiple_chunks = n > 1
    total = n + 3 + (1 if has_multiple_chunks else 0)
    done = 0
    current_stage = "read"
    stage_order = {stage: i for i, stage in enumerate(
        ("read", "cites", "review", "summary", "global", "verdict")
    )}
    progress_lock = threading.Lock()

    def run_stage(stage, msg, task):
        nonlocal done, current_stage
        started = time.perf_counter()
        with progress_lock:
            if stage_order[stage] > stage_order[current_stage]:
                current_stage = stage
            update(current_stage, done / total, msg)
        try:
            return task()
        finally:
            elapsed = time.perf_counter() - started
            with progress_lock:
                done += 1
                if stage_order[stage] > stage_order[current_stage]:
                    current_stage = stage
                update(current_stage, done / total, f"{msg} · {elapsed:.1f}s")
            _logger.info("%s completed in %.1f seconds", msg, elapsed)

    def review_chunk(i, chunk):
        label = f"Reviewing part {i}/{n}: {chunk['label']}"
        def review():
            data = llm.chat_json(
                prompts.REVIEWER,
                prompts.critique(doc["abstract"], chunk["label"], chunk["text"]),
                max_new_tokens=1800,
            )
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("digest"), str)
                or not data["digest"].strip()
            ):
                raise RuntimeError(f"Gemini returned an invalid review for section {chunk['label']}.")
            return f"[{chunk['label']}] {data['digest'].strip()}", collect(
                data,
                folded,
                chunk["start"],
                chunk["end"],
                chunk["label"],
            )

        return run_stage(
            "review",
            label,
            review,
        )

    pool = ThreadPoolExecutor(max_workers=config.GEMINI_CONCURRENCY)
    citation_pool = ThreadPoolExecutor(max_workers=1)
    try:
        citation_future = citation_pool.submit(
            run_stage,
            "cites",
            "Parsing references and checking in-text citations" + (" against Crossref" if online else ""),
            lambda: citations.analyze(text, doc, online, config.CROSSREF_MAILTO),
        )
        review_futures = {}
        for i, chunk in enumerate(chunks, 1):
            future = pool.submit(review_chunk, i, chunk)
            review_futures[future] = i - 1

        digests = [None] * n
        found = []
        for future in as_completed(review_futures):
            index = review_futures[future]
            digest_text, chunk_findings = future.result()
            digests[index] = digest_text
            found.extend(chunk_findings)

        body = "\n\n".join(digests) if has_multiple_chunks else chunks[0]["text"]
        is_digest = has_multiple_chunks
        summary_future = pool.submit(
            run_stage,
            "summary",
            "Writing the summary",
            lambda: llm.chat_json(
                prompts.REVIEWER,
                prompts.summary(doc["abstract"], body, is_digest),
                max_new_tokens=1600,
            ) or {},
        )

        cross_future = None
        if has_multiple_chunks:
            cross_future = pool.submit(
                run_stage,
                "global",
                "Cross-checking claims against evidence across sections",
                lambda: collect(
                    llm.chat_json(
                        prompts.REVIEWER,
                        prompts.cross_check(doc["abstract"], doc["conclusion"], "\n\n".join(digests)),
                        max_new_tokens=2048,
                    ),
                    folded,
                    0,
                    len(folded),
                    "Whole paper",
                ),
            )

        if cross_future:
            found.extend(cross_future.result())
        cites = citation_future.result()
        s = summary_future.result()
        summary = {
            "title": str(s.get("title", "")).strip() or name,
            "tldr": str(s.get("tldr", "")).strip(),
            "research_question": str(s.get("research_question", "")).strip(),
            "approach": str(s.get("approach", "")).strip(),
            "key_findings": as_list(s.get("key_findings")),
            "contributions": as_list(s.get("contributions")),
            "stated_limitations": as_list(s.get("stated_limitations")),
            "keywords": as_list(s.get("keywords")),
        }
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        citation_pool.shutdown(wait=True, cancel_futures=True)

    findings = dedupe(found)

    with progress_lock:
        current_stage = "verdict"
        update(current_stage, done / total, "Forming the overall assessment")
    verdict_started = time.perf_counter()
    listing = "\n".join(f"#{f['id']} [{f['severity']}] {f['category']}: {f['title']}" for f in findings[:40] if f["grounded"]) or "(no confirmed findings)"
    v = llm.chat_json(
        prompts.REVIEWER,
        prompts.verdict(summary["tldr"] or summary["research_question"], listing),
        max_new_tokens=1200,
    ) or {}
    verdict_elapsed = time.perf_counter() - verdict_started
    _logger.info("Overall assessment completed in %.1f seconds", verdict_elapsed)
    crit = sum(1 for f in findings if f["grounded"] and f["severity"] == "critical")
    major = sum(1 for f in findings if f["grounded"] and f["severity"] == "major")
    rec = str(v.get("recommendation", "")).lower().strip()
    if rec not in RECS:
        rec = "major revision" if crit or major > 2 else "minor revision"
    review = {
        "overall": str(v.get("overall_assessment", "")).strip(),
        "strengths": as_list(v.get("strengths")),
        "priorities": as_list(v.get("priority_fixes")),
        "recommendation": rec,
        "findings": findings,
    }
    with progress_lock:
        done += 1
        progress = done / total
        update(current_stage, progress, f"Overall assessment · {verdict_elapsed:.1f}s")
    update("done", 1.0, "Done")

    return {
        "meta": {
            "filename": name,
            "words": len(text.split()),
            "parts": n,
            "model": config.MODEL_ID,
            "heads": doc["heads"],
            "sections": [s for s in doc["sections"]],
        },
        "text": text,
        "summary": summary,
        "review": review,
        "citations": cites,
    }
