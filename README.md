# Reacher

**An AI-powered research paper reviewer that turns complex academic papers into structured, evidence-backed insights.**

Reacher is an AI-assisted research paper analysis tool built to help students and researchers understand, evaluate, and review academic papers more effectively.

Upload a research paper or a collection of papers, and Reacher uses Google's Gemma models through the Gemini API to analyse research methodology, identify potential weaknesses, evaluate claims, inspect references, generate summaries, and answer follow-up questions using relevant passages from the paper.

Rather than simply generating a generic summary, Reacher focuses on **contextual analysis, evidence-grounded feedback, and research transparency.**

> Reacher is designed as a research and study assistant. Its findings should be independently verified and are not a replacement for expert peer review.

---

## ✨ Key Features

### 1. AI-Powered Research Analysis
- Analyses research papers across multiple dimensions:
  - Research methodology
  - Statistical reasoning
  - Logical consistency
  - Claims and supporting evidence
  - Data quality
  - Reproducibility
  - Citation accuracy
  - Research ethics
  - Clarity and presentation
- Classifies findings by severity: Critical, Major, and Minor.
- Provides explanations and actionable suggestions for identified issues.

### 2. Evidence-Grounded Findings
- Every reported issue is expected to include a direct quotation from the paper.
- Matches quoted passages against extracted document text.
- Tracks whether a finding can be located in the original extracted content.
- Helps readers inspect the context behind individual findings instead of relying on unsupported AI-generated criticism.

### 3. Intelligent Paper Summarisation
Generates structured summaries containing:
- Research question
- Research approach
- Key findings
- Main contributions
- Stated limitations
- Relevant keywords

### 4. Cross-Section Consistency Analysis
- Compares the abstract and conclusion against the rest of the paper.
- Identifies possible contradictions and unsupported claims.
- Highlights overgeneralisation and conclusions that may exceed the reported evidence.

### 5. Citation & Reference Verification
- Analyses in-text citations and reference lists.
- Identifies potentially missing, uncited, or duplicate references.
- Supports author-year and numbered citation patterns.
- Integrates with Crossref for optional reference metadata checks.
- Distinguishes strong matches from ambiguous or unresolved references.

### 6. Paper-Based AI Q&A
Ask questions about an uploaded research paper and receive answers grounded in its content.

- Retrieves relevant passages using keyword-based selection.
- Uses selected paper excerpts as the model's context.
- Provides references to supporting passages.
- Avoids guessing when sufficient evidence cannot be found.

### 7. Batch Paper Processing
- Upload multiple research papers together.
- Review each paper independently.
- Track individual processing status and progress.
- Preserve successful results even if another paper in the batch fails.

### 8. Asynchronous Processing
- Background review jobs prevent long-running analysis from blocking the application interface.
- Concurrent model calls help process long papers more efficiently.
- Configurable concurrency and retry handling help manage API rate limits.

---

## ⚙️ How It Works

Reacher follows a multi-stage document analysis pipeline.

| Stage | Process |
|---|---|
| 01. Extraction | Extracts text from PDF, DOCX, TXT, and Markdown documents. |
| 02. Structuring | Identifies academic sections and separates reference content. |
| 03. Chunking | Splits long documents into manageable sections for analysis. |
| 04. AI Review | Uses Gemma to analyse individual sections and identify potential weaknesses. |
| 05. Grounding | Attempts to locate quoted evidence in the extracted paper text. |
| 06. Cross-Checking | Compares abstract, conclusion, and section-level findings. |
| 07. Citation Analysis | Checks citation consistency and optionally queries Crossref. |
| 08. Summarisation | Generates a structured summary and overall assessment. |
| 09. Paper Q&A | Retrieves relevant passages to answer follow-up questions. |

The pipeline is designed to make AI-generated feedback easier to inspect and verify.

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| Backend | Python |
| API Framework | FastAPI |
| Server | Uvicorn |
| AI Models | Google Gemma |
| AI Integration | Gemini API / Google Gen AI SDK |
| PDF Processing | PyMuPDF |
| DOCX Processing | python-docx |
| HTTP Client | HTTPX |
| Environment Management | python-dotenv |
| Frontend | HTML, CSS, JavaScript |
| Reference Metadata | Crossref API |

---

## 📁 Project Structure

```text
static-web/
│
├── app/
│   ├── __init__.py
│   ├── analysis.py       # Research analysis and finding validation
│   ├── citations.py      # Citation parsing and Crossref integration
│   ├── config.py         # Application configuration
│   ├── llm.py            # Gemini API and Gemma model integration
│   ├── main.py           # FastAPI application and API endpoints
│   ├── parse.py          # Document extraction and section parsing
│   ├── prompts.py        # AI prompts and response schemas
│   └── questions.py      # Paper-based Q&A and passage retrieval
│
├── static/
│   ├── app.js            # Frontend application logic
│   ├── index.html        # Main application interface
│   └── style.css         # Frontend styling
│
├── .env.example          # Example environment variables
├── .gitignore
├── README.md
├── requirements.txt
└── run.py                # Application entry point
```

---

## 🚀 Getting Started

Follow these steps to run Reacher locally.

### Prerequisites

Make sure you have:

- Python 3.10 or newer.
- A Gemini API key.
- Internet connectivity for AI inference and optional Crossref verification.

No local GPU or model installation is required.

### 1. Clone the Repository

```bash
git clone https://github.com/creatorhere/static-web.git
cd static-web
```

### 2. Create a Virtual Environment

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file from the provided example.

**Windows**

```powershell
Copy-Item .env.example .env
```

**Linux / macOS**

```bash
cp .env.example .env
```

Add your Gemini API key:

```env
GEMINI_API_KEY=your_gemini_api_key
```

Get your API key from:

[Google AI Studio – API Keys](https://aistudio.google.com/apikey)

**Important:** Never commit your `.env` file, API keys, or private credentials to GitHub.

### 5. Run the Application

```bash
python run.py
```

The application starts the local FastAPI server and attempts to open your default browser.

Access Reacher at:

**http://127.0.0.1:8000**

---

## 🔧 Configuration

Reacher supports environment-based configuration through the `.env` file.

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini API authentication key |
| `GOOGLE_API_KEY` | — | Alternative API key variable |
| `GEMMA_MODEL` | `gemma-4-26b-a4b-it` | Model used for analysis |
| `MAX_NEW_TOKENS` | `4096` | Maximum model output tokens |
| `CHUNK_CHARS` | `8000` | Target chunk size for document processing |
| `GEMINI_CONCURRENCY` | `3` | Maximum concurrent model calls |
| `MAX_UPLOAD_MB` | `200` | Maximum individual upload size |
| `MAX_BATCH_FILES` | `10` | Maximum papers per batch |
| `MAX_BATCH_MB` | `512` | Maximum combined batch size |
| `CROSSREF_MAILTO` | — | Optional email for Crossref requests |
| `PORT` | `8000` | Local application port |

Example configuration:

```env
GEMINI_API_KEY=your_gemini_api_key

GEMMA_MODEL=gemma-4-26b-a4b-it
GEMINI_CONCURRENCY=3

MAX_UPLOAD_MB=200
MAX_BATCH_FILES=10
MAX_BATCH_MB=512

PORT=8000
```

If you encounter Gemini API rate limits, try reducing `GEMINI_CONCURRENCY` to `1` or `2`.

---

## 📄 Supported File Formats

| Format | Extension | Support |
|---|---|---|
| PDF | `.pdf` | Text extraction using PyMuPDF |
| Microsoft Word | `.docx` | Paragraph extraction |
| Plain Text | `.txt` | Text-based analysis |
| Markdown | `.md` | Text-based analysis |

Multiple supported documents can be submitted together through batch processing.

---

## 🔐 Privacy & Data Handling

Reacher uses external services for AI inference and optional reference verification.

- Uploaded paper text is sent to the Gemini API for analysis.
- Paper Q&A sends questions, recent conversation context, and selected paper passages to Gemini.
- Optional Crossref verification sends reference strings to Crossref.
- Individual review results are held in server memory while the application is running.
- Batch results and extracted text are stored in temporary files and removed when the application exits.
- The current implementation does not use a database for review storage.

Do not upload confidential, copyrighted, or sensitive research documents unless you have permission to share them with the relevant external services.

---

## ⚠️ Current Limitations

- **Scanned PDFs:** OCR is not currently included. Image-only PDFs require OCR before processing.
- **Figures and tables:** Analysis relies on extracted text, so visual information may be missed.
- **Model accuracy:** AI-generated findings may be incomplete or incorrect and require human verification.
- **Reference coverage:** Crossref does not index every publication. An unresolved match does not necessarily indicate an invalid reference.
- **Q&A retrieval:** Passage selection currently uses keyword-based retrieval and may miss relevant content expressed with different terminology.
- **API limits:** Large papers and batches can take time and consume Gemini API quota.

---

## 🎯 Project Objective

Reacher was developed as a practical exploration of how generative AI can support academic research and critical reading.

The goal is not simply to summarise research papers, but to make the review process more structured, transparent, and useful by connecting AI-generated observations to the actual content of a document.

---

## 🤝 Contributing

Contributions, suggestions, and improvements are welcome.

If you find a bug or have an idea for improving Reacher:

1. Fork the repository.
2. Create a feature branch.
3. Make your changes.
4. Submit a pull request describing the improvement.

For significant changes, consider opening an issue first to discuss the proposed approach.

---

## 📜 License

No license has currently been specified for this repository. Unless a license is added, the default copyright protections apply; reuse and redistribution should not be assumed to be permitted.

---

**Built with Python, FastAPI, and Gemma.**  
*Making research review more structured, transparent, and accessible.*
