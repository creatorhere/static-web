import difflib
import logging
import re
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import quote

import httpx

_logger = logging.getLogger(__name__)
YEAR = re.compile(r"\b(?P<year>19[5-9]\d|20[0-4]\d)(?P<suffix>[a-z])?\b", re.I)
DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s\"<>]+)", re.I)
NUM = re.compile(r"\[(\d{1,3}(?:\s*[,\u2013\-]\s*\d{1,3})*)\]")
NAME = r"[A-Z][A-Za-z'\u2019\-]+"
AY = re.compile(rf"(?P<a>{NAME})(?:\s+(?:et al\.?|(?:and|&)\s+{NAME}))?,?\s+(?P<y>(?:19|20)\d{{2}})(?P<suffix>[a-z])?")
NARR = re.compile(rf"(?P<a>{NAME})(?:\s+(?:et al\.?|(?:and|&)\s+{NAME}))?\s*\((?P<y>(?:19|20)\d{{2}})(?P<suffix>[a-z])?\)")
PAREN = re.compile(r"\(([^()]{4,300})\)")
SPLIT_AY = re.compile(rf"(?<=[.)\d]\s)(?={NAME},\s(?:[A-Z]\.\s?){{1,3}})")


def split_refs(t):
    t = t.strip()
    if not t:
        return []
    if len(re.findall(r"(?:^|\s)\[\d{1,3}\]\s", t)) >= 3:
        out = []
        for part in re.split(r"(?=(?:^|\s)\[\d{1,3}\]\s)", t):
            m = re.match(r"\s*\[(\d{1,3})\]\s*(.*)", part, re.S)
            if m and len(m.group(2)) > 20:
                out.append((int(m.group(1)), " ".join(m.group(2).split())))
        return out
    pieces = []
    numbered = len(re.findall(r"(?:^|\s)\d{1,3}\.\s+[A-Z]", t)) >= 5
    for p in t.split("\n\n"):
        parts = re.split(r"\s(?=\d{1,3}\.\s+[A-Z])", p) if numbered else [p]
        for q in parts:
            pieces += SPLIT_AY.split(q)
    pieces = [" ".join(p.split()) for p in pieces if len(p.strip()) > 25]
    nums = [re.match(r"^(\d{1,3})[.)]\s+", p) for p in pieces]
    if pieces and sum(1 for m in nums if m) >= 0.6 * len(pieces):
        return [(int(m.group(1)), p[m.end():]) if m else (i + 1, p) for i, (m, p) in enumerate(zip(nums, pieces))]
    return [(i + 1, p) for i, p in enumerate(pieces)]


def parse_refs(refs_text):
    refs = []
    for n, raw in split_refs(refs_text):
        y = YEAR.search(raw)
        d = DOI.search(raw)
        doi = d.group(1).rstrip(".,;:!?)]}") if d else None
        prefix = raw[:y.start()] if y else raw[:120]
        authors = re.findall(r"\b[A-Z][A-Za-z'\u2019\-]{1,}\b", prefix)
        refs.append({
            "n": n,
            "raw": raw,
            "year": int(y.group("year")) if y else None,
            "year_suffix": y.group("suffix").lower() if y and y.group("suffix") else "",
            "doi": doi,
            "first_author": authors[0].casefold() if authors else None,
            "cites": 0,
            "flags": [],
            "status": "pending",
            "match": None,
        })
    return refs


def expand(token):
    out = []
    for part in re.split(r"\s*,\s*", token):
        m = re.match(r"(\d+)\s*[\u2013\-]\s*(\d+)$", part)
        if m and 0 < int(m.group(2)) - int(m.group(1)) < 50:
            out += list(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def in_text(masked):
    numeric, author = [], []
    for m in NUM.finditer(masked):
        for n in expand(m.group(1)):
            numeric.append((n, m.start()))
    for m in PAREN.finditer(masked):
        inner = m.group(1)
        if not YEAR.search(inner):
            continue
        for part in inner.split(";"):
            a = AY.search(part)
            if a:
                author.append((a.group("a"), int(a.group("y")), (a.group("suffix") or "").lower(), m.start()))
    for m in NARR.finditer(masked):
        author.append((m.group("a"), int(m.group("y")), (m.group("suffix") or "").lower(), m.start()))
    return numeric, author


def judge(ref, item, via):
    title = " ".join(item.get("title") or [""]).strip()
    title_tokens = set(re.findall(r"[a-z0-9]{3,}", title.casefold()))
    raw_tokens = set(re.findall(r"[a-z0-9]{3,}", ref["raw"].casefold()))
    title_score = len(title_tokens & raw_tokens) / max(len(title_tokens), 1)
    doi = (item.get("DOI") or "").strip().casefold()
    doi_match = bool(ref["doi"] and doi == ref["doi"].casefold())
    authors = item.get("author") or []
    first_author = (
        str(authors[0].get("family", "")).casefold()
        if authors and isinstance(authors[0], dict)
        else None
    )
    author_match = bool(ref["first_author"] and first_author and ref["first_author"] == first_author)
    parts = (item.get("issued") or {}).get("date-parts") or [[None]]
    cy = parts[0][0] if parts and parts[0] else None
    year_delta = abs(ref["year"] - cy) if ref["year"] and cy else None
    year_match = year_delta is None or year_delta <= 1

    if doi_match and title_score >= 0.75 and year_match and (author_match or not ref["first_author"] or not first_author):
        status = "verified"
        reason = "DOI, title, author, and year are consistent."
    elif doi_match and title and title_score < 0.5:
        status = "mismatch"
        reason = "The DOI resolves, but its title differs from the cited title."
    elif doi_match and year_delta is not None and year_delta > 1:
        status = "mismatch"
        reason = "The DOI resolves, but its publication year differs from the cited year."
    elif doi_match and ref["first_author"] and first_author and not author_match:
        status = "mismatch"
        reason = "The DOI resolves, but its first author differs from the cited author."
    elif not doi_match and title_score >= 0.82 and author_match and year_match:
        status = "verified"
        reason = "Title, first author, and year match the Crossref record."
    else:
        status = "unverified"
        reason = "The closest Crossref result did not match the title, first author, and year strongly enough."
    return status, {
        "title": title,
        "doi": item.get("DOI"),
        "year": cy,
        "first_author": first_author,
        "title_score": round(title_score, 2),
        "author_match": author_match,
        "year_match": year_match,
        "doi_match": doi_match,
        "via": via,
        "reason": reason,
    }


def _crossref_match(ref, items):
    ranked = []
    for item in items:
        status, match = judge(ref, item, "doi" if ref["doi"] else "bibliographic search")
        rank = (
            int(match["doi_match"]),
            int(status == "verified"),
            int(match["author_match"]),
            int(match["year_match"]),
            match["title_score"],
        )
        ranked.append((rank, status, match))
    if not ranked:
        return "unverified", None
    _, status, match = max(ranked, key=lambda result: result[0])
    return status, match


def verify_one(ref, client):
    doi_not_found = False
    try:
        if ref["doi"]:
            doi = quote(ref["doi"], safe="/")
            r = client.get(f"https://api.crossref.org/works/{doi}")
            if r.status_code == 200:
                ref["status"], ref["match"] = _crossref_match(ref, [r.json()["message"]])
                if ref["status"] == "mismatch":
                    ref["flags"].append(ref["match"]["reason"])
                return
            if r.status_code not in {404, 410}:
                ref["status"] = "skipped"
                ref["flags"].append(f"Crossref lookup failed (HTTP {r.status_code})")
                return
            doi_not_found = True
        r = client.get(
            "https://api.crossref.org/works",
            params={
                "query.bibliographic": ref["raw"][:300],
                "rows": 5,
                "select": "title,author,issued,DOI,score",
            },
        )
        items = r.json().get("message", {}).get("items", []) if r.status_code == 200 else []
        if items:
            ref["status"], ref["match"] = _crossref_match(ref, items)
            if doi_not_found and ref["status"] == "verified":
                ref["status"] = "unverified"
                ref["match"]["reason"] = "The title, author, and year match, but the supplied DOI did not resolve in Crossref."
                ref["flags"].append(ref["match"]["reason"])
        else:
            ref["status"] = "skipped" if r.status_code == 429 or r.status_code >= 500 else "unverified"
            if ref["status"] == "skipped":
                ref["flags"].append(f"Crossref lookup failed (HTTP {r.status_code})")
            else:
                reason = "The supplied DOI did not resolve in Crossref." if doi_not_found else "No close Crossref record was found."
                ref["flags"].append(reason)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        _logger.warning("Crossref verification failed for reference %s: %s", ref["n"], exc)
        ref["status"] = "skipped"
        ref["flags"].append(f"Crossref could not verify this reference: {exc}")


def verify_all(refs, mailto):
    ua = f"Reacher/1.0 (mailto:{mailto})" if mailto else "Reacher/1.0"
    with httpx.Client(timeout=12, headers={"User-Agent": ua}) as client:
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda r: verify_one(r, client), refs[:80]))
    for r in refs[80:]:
        r["status"] = "skipped"
        r["flags"].append("Crossref lookup limit reached (80 references per paper)")


def analyze(text, doc, online, mailto):
    masked = list(text)
    for a, b in doc["ref_ranges"]:
        masked[a:b] = " " * (b - a)
    masked = "".join(masked)

    refs = parse_refs(doc["refs_text"])
    out = {"found": bool(refs), "style": "unknown", "references": refs, "issues": [], "histogram": [], "stats": {}}
    numeric, author = in_text(masked)

    if not refs:
        out["issues"].append({"type": "missing", "text": "No reference list could be located in this document.", "pos": None})
        out["stats"] = {"references": 0, "in_text": len(numeric) + len(author)}
        return out

    style = "numeric" if len(numeric) >= len(author) else "author-year"
    out["style"] = style
    by_n = {r["n"]: r for r in refs}
    max_n = max(by_n)
    total = 0
    dangling = 0

    if style == "numeric":
        seen = {}
        for n, pos in numeric:
            total += 1
            seen.setdefault(n, pos)
            if n in by_n:
                by_n[n]["cites"] += 1
        for n, pos in sorted(seen.items()):
            if n not in by_n:
                dangling += 1
                out["issues"].append({"type": "dangling", "text": f"Citation [{n}] has no matching entry (the list ends at [{max_n}]).", "pos": pos})
    else:
        seen = {}
        for a, y, suffix, pos in author:
            total += 1
            hits = [
                r for r in refs
                if r["year"] == y
                and r["first_author"] == a.casefold()
                and (not suffix or r["year_suffix"] == suffix)
            ]
            if len(hits) == 1:
                r = hits[0]
                r["cites"] += 1
            elif len(hits) > 1:
                seen.setdefault(("ambiguous", a, y, suffix), pos)
            elif not any(
                r["year"] == y and r["first_author"] == a.casefold()
                and (not suffix or r["year_suffix"] == suffix)
                for r in refs
            ):
                seen.setdefault(("dangling", a, y, suffix), pos)
        for (kind, a, y, suffix), pos in seen.items():
            dangling += 1
            if kind == "ambiguous":
                text = f"In-text citation “{a} {y}{suffix}” matches multiple references; add year suffixes to disambiguate."
            else:
                text = f"In-text citation “{a} {y}{suffix}” has no matching reference."
            out["issues"].append({"type": kind, "text": text, "pos": pos})

    uncited = 0
    for r in refs:
        if r["cites"] == 0:
            uncited += 1
            r["flags"].append("never cited in the text")
            out["issues"].append({"type": "uncited", "text": f"Reference {r['n']} is listed but never cited.", "pos": None})
        if r["year"] is None:
            r["flags"].append("no year found")

    low = [r["raw"][:160].lower() for r in refs]
    for i in range(len(refs)):
        for j in range(i + 1, len(refs)):
            if difflib.SequenceMatcher(None, low[i], low[j]).quick_ratio() > 0.9 and difflib.SequenceMatcher(None, low[i], low[j]).ratio() > 0.92:
                refs[j]["flags"].append(f"possible duplicate of {refs[i]['n']}")
                out["issues"].append({"type": "duplicate", "text": f"References {refs[i]['n']} and {refs[j]['n']} look like duplicates.", "pos": None})

    if online:
        verify_all(refs, mailto)
        for r in refs:
            if r["status"] == "mismatch":
                out["issues"].append({"type": "mismatch", "text": f"Reference {r['n']}: {r['match']['reason'] if r['match'] else 'the Crossref record does not match the citation.'}", "pos": None})
    else:
        for r in refs:
            r["status"] = "skipped"

    years = [r["year"] for r in refs if r["year"]]
    now = date.today().year
    counts = Counter(r["status"] for r in refs)
    out["histogram"] = sorted(Counter(years).items())
    out["stats"] = {
        "references": len(refs),
        "in_text": total,
        "dangling": dangling,
        "uncited": uncited,
        "verified": counts["verified"],
        "mismatch": counts["mismatch"],
        "unverified": counts["unverified"],
        "skipped": counts["skipped"],
        "online": online,
        "median_year": int(statistics.median(years)) if years else None,
        "recent_share": round(sum(1 for y in years if y >= now - 5) / len(years), 2) if years else None,
        "oldest": min(years) if years else None,
        "newest": max(years) if years else None,
    }
    return out
