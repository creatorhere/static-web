# Reacher

Reacher is my semester project. I wanted a tool that could help me review research papers and point out issues in context, but I couldn't find one that worked the way I wanted. So I decided to build it for myself.

Upload one paper or a bundle and Reacher uses Gemma 4 to identify potential issues, anchor feedback to quoted passages, suggest fixes, summarise the paper, check its references, and answer follow-up questions using relevant paper passages. It's a study aid and first-pass reviewer, not a substitute for your own judgment.

Gemma 4 is called through the **Gemini API** (Google AI Studio), so there is nothing to download and no GPU is needed.

## Setup

1. Get a free API key at https://aistudio.google.com/apikey
2. Copy `.env.example` to `.env` and paste the key:
   ```
   GEMINI_API_KEY=your_key_here
   ```
3. Install and run:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python run.py
   ```

The browser opens at http://127.0.0.1:8000. The status pill (top right) turns green when the key is loaded. Hover over it if it turns red.

## Models

Set `GEMMA_MODEL` in `.env`.

| Model id | Notes |
|---|---|
| `gemma-4-26b-a4b-it` (default) | faster, lighter on rate limits |
| `gemma-4-31b-it` | strongest critique |

Other settings: `MAX_NEW_TOKENS` (4096), `CHUNK_CHARS` (8000), `GEMINI_CONCURRENCY` (3 simultaneous model calls), `MAX_UPLOAD_MB` (200 per paper), `MAX_BATCH_FILES` (10), `MAX_BATCH_MB` (512 per bundle), `CROSSREF_MAILTO` (your email, for Crossref), and `PORT` (8000). Select or drop multiple PDF, DOCX, TXT, or MD files to review a bundle. Bundle reviews run one paper at a time; each paper has its own result, and a failed file does not discard successful reviews. Only one bundle can run at a time. Individual uploads are streamed to temporary files instead of being copied into application memory. Batch review results and extracted text are stored in the system temporary directory while Reacher is running and removed when it exits; individual review results remain in memory. Long-paper chunk reviews run concurrently, and each chunk now produces its factual notes and critique in one model call. The summary and cross-section check run together while citation checks overlap with model work. Large bundles may take a long time and use substantial Gemini API quota; each paper is reviewed separately. If you hit 429 rate limits, lower `GEMINI_CONCURRENCY` in `.env` to `1` or `2`; transient errors use jittered backoff, honor retry hints when possible, and cap cumulative retry delays at 60 seconds. The Gemini SDK's automatic retries are disabled so this single retry policy controls waiting. Timings for completed pipeline stages are logged.

## How it stays accurate

1. **Parsing.** PDF text is read block by block with column-aware ordering. Headers, footers and the reference list are separated from the body.
2. **Chunked review.** Long papers are split along section boundaries. Each chunk is reviewed with the abstract as context.
3. **Verbatim anchoring.** Every finding must quote the paper. The quote is located in the document text, so each flaw is highlighted in place. Findings whose quote cannot be found are hidden by default and flagged as unverified.
4. **Cross-section pass.** A separate pass compares abstract and conclusion claims against the rest of the paper, to catch overclaiming and contradictions.
5. **Deduplication, severity ranking, and a calibrated verdict** built only from the confirmed findings.
6. **Citations.** In-text markers (`[3]`, `[1–4]`, `(Smith et al., 2020)`) are matched to the reference list to find dangling and uncited entries and duplicates. Author-year citations require an exact first-author surname and year match; ambiguous same-author/year references are reported rather than silently assigned. Optional Crossref checks compare candidate title, first author, year, and any supplied DOI, ranking multiple search results instead of trusting the first hit. Only strong multi-field matches are called verified; unresolved matches and lookup failures are reported separately and are not treated as proof a source is fabricated.
7. **Paper Q&A.** Ask follow-up questions after a review. Reacher selects relevant text passages, answers from those excerpts, and links cited evidence back to its location in the paper. If it cannot find enough support, it says so rather than guessing.

## Network use

The paper text is sent to the Gemini API for analysis, so don't upload anything you are not allowed to share with Google. Paper Q&A sends your question, recent conversation context, and selected paper excerpts to Gemini. The optional Crossref lookup sends only reference strings (untick the box in the UI to disable it). Individual reviews are held in server memory while the app runs and are not saved to a database. Bundle reviews and extracted paper text use temporary files while the app runs; these files are removed when the app exits.

## Limits

- Scanned PDFs need OCR first. No OCR is included.
- Upload limits default to 200 MB per paper and 10 papers / 512 MB per bundle. You can raise or lower them in `.env`, but larger files use more disk, memory, and Gemini API quota; image-only scanned PDFs still need OCR.
- The model can still miss flaws or misjudge them. Treat the output as a thorough first reviewer, not a verdict. The quote and fix are always shown so you can check each one.
- "Unverified" on a reference means no close Crossref match. Preprints, books and many conference papers are not indexed there.
- Equations, tables and figures are only seen as extracted text.
- Q&A uses keyword-based passage selection, so it may miss evidence expressed with different terminology.

## Layout

```
run.py            launcher
app/main.py       FastAPI server and job runner
app/analysis.py   review pipeline, quote grounding, dedupe
app/questions.py  paper-grounded Q&A and passage selection
app/prompts.py    all prompts
app/parse.py      PDF/DOCX/TXT reading and section chunking
app/citations.py  reference parsing, cross-checks, Crossref
app/llm.py        Gemma 4 via the Gemini API (google-genai)
static/           the UI
```
