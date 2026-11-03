import os

from dotenv import load_dotenv

load_dotenv()

MODEL_ID = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "4096"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "8000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))
MAX_BATCH_FILES = int(os.getenv("MAX_BATCH_FILES", "10"))
MAX_BATCH_MB = int(os.getenv("MAX_BATCH_MB", "512"))
GEMINI_CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", "3"))
if MAX_UPLOAD_MB < 1:
    raise ValueError("MAX_UPLOAD_MB must be at least 1.")
if MAX_BATCH_FILES < 2:
    raise ValueError("MAX_BATCH_FILES must be at least 2.")
if MAX_BATCH_MB < 1:
    raise ValueError("MAX_BATCH_MB must be at least 1.")
if GEMINI_CONCURRENCY < 1:
    raise ValueError("GEMINI_CONCURRENCY must be at least 1.")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO", "")
PORT = int(os.getenv("PORT", "8000"))
