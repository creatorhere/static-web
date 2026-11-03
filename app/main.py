import json
import os
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analysis, config, llm, questions

STATIC = Path(__file__).resolve().parent.parent / "static"
ALLOWED = {".pdf", ".docx", ".txt", ".md"}
JOBS = {}
_RESULTS_DIR = tempfile.TemporaryDirectory(prefix="reacher-results-")
BATCHES = {}
_BATCH_SLOT = threading.BoundedSemaphore(1)
UPLOAD_CHUNK_BYTES = 1024 * 1024
MAX_RETAINED_JOBS = 15
MAX_RETAINED_BATCHES = 3


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=8)


class Job:
    def __init__(self, name, persist_result=False):
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.persist_result = persist_result
        self.status = "running"
        self.stage = "read"
        self.progress = 0.0
        self.log = []
        self.result = None
        self.error = ""
        self.created = time.time()
        self.result_path = None
        self.text_path = None

    def update(self, stage, progress, msg=None):
        self.stage = stage
        self.progress = round(progress, 3)
        if msg:
            self.log.append(msg)


class Batch:
    def __init__(self, jobs):
        self.id = uuid.uuid4().hex[:12]
        self.jobs = jobs
        self.created = time.time()


def _persist_result(job, result):
    result_data = dict(result)
    text = result_data.pop("text")
    result_path = os.path.join(_RESULTS_DIR.name, f"{job.id}.json")
    text_path = os.path.join(_RESULTS_DIR.name, f"{job.id}.txt")
    try:
        with open(result_path, "w", encoding="utf-8") as file:
            json.dump(result_data, file, ensure_ascii=False)
        with open(text_path, "w", encoding="utf-8") as file:
            file.write(text)
    except (OSError, TypeError):
        for saved_path in (result_path, text_path):
            try:
                os.remove(saved_path)
            except FileNotFoundError:
                pass
        raise
    job.result_path = result_path
    job.text_path = text_path


def _load_result(job):
    if job.result is not None:
        return job.result
    if job.result_path and job.text_path:
        with open(job.result_path, encoding="utf-8") as file:
            result = json.load(file)
        with open(job.text_path, encoding="utf-8") as file:
            result["text"] = file.read()
        return result
    raise RuntimeError("The completed review is no longer available.")


def _load_text(job):
    if job.result is not None:
        return job.result["text"]
    if job.text_path:
        with open(job.text_path, encoding="utf-8") as file:
            return file.read()
    raise RuntimeError("The paper text is no longer available.")


def _remove_job(job):
    JOBS.pop(job.id, None)
    for path in (job.result_path, job.text_path):
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass


def _batch_status(batch):
    statuses = [job.status for job in batch.jobs]
    if any(status in {"queued", "running"} for status in statuses):
        return "running"
    if any(status == "done" for status in statuses):
        return "done"
    return "error"


def _prune_batches():
    completed = sorted(
        (batch for batch in BATCHES.values() if _batch_status(batch) != "running"),
        key=lambda batch: batch.created,
    )
    while len(BATCHES) >= MAX_RETAINED_BATCHES and completed:
        batch = completed.pop(0)
        BATCHES.pop(batch.id, None)
        for job in batch.jobs:
            _remove_job(job)


def _prune_jobs():
    batch_job_ids = {job.id for batch in BATCHES.values() for job in batch.jobs}
    old_jobs = sorted(
        (
            job for job in JOBS.values()
            if job.id not in batch_job_ids and job.status in {"done", "error"}
        ),
        key=lambda job: job.created,
    )
    while len(JOBS) > MAX_RETAINED_JOBS and old_jobs:
        _remove_job(old_jobs.pop(0))


def _safe_filename(filename):
    return Path(filename.replace("\\", "/")).name or "paper"


async def _save_upload(upload):
    filename = _safe_filename(upload.filename or "paper")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED:
        await upload.close()
        raise HTTPException(400, f"{filename}: upload a PDF, DOCX, TXT or MD file.")
    fd, path = tempfile.mkstemp(suffix=ext)
    size = 0
    try:
        with os.fdopen(fd, "wb") as file:
            while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(413, f"{filename} is larger than {config.MAX_UPLOAD_MB} MB.")
                file.write(chunk)
        return filename, path, size
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    finally:
        await upload.close()


def work(job, path, online):
    try:
        job.status = "running"
        job.update("read", 0.0, "Reading the document")
        result = analysis.analyze(path, job.name, online, job.update)
        if job.persist_result:
            _persist_result(job, result)
        else:
            job.result = result
        job.status = "done"
    except Exception as e:
        traceback.print_exc()
        job.status, job.error = "error", str(e)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def work_batch(batch, paths, online):
    try:
        for job, path in zip(batch.jobs, paths):
            if path:
                work(job, path, online)
    finally:
        _BATCH_SLOT.release()


@asynccontextmanager
async def lifespan(_):
    threading.Thread(target=llm.preload, daemon=True).start()
    try:
        yield
    finally:
        _RESULTS_DIR.cleanup()


app = FastAPI(title="Reacher", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {
        **llm.status,
        "limits": {
            "max_file_mb": config.MAX_UPLOAD_MB,
            "max_batch_files": config.MAX_BATCH_FILES,
            "max_batch_mb": config.MAX_BATCH_MB,
        },
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), verify_online: bool = Form(True)):
    filename, path, _ = await _save_upload(file)
    job = Job(filename)
    JOBS[job.id] = job
    _prune_jobs()
    threading.Thread(target=work, args=(job, path, verify_online), daemon=True).start()
    return {"job_id": job.id}


@app.post("/api/analyze-batch")
async def analyze_batch(files: list[UploadFile] = File(...), verify_online: bool = Form(True)):
    if not 1 < len(files) <= config.MAX_BATCH_FILES:
        for upload in files:
            await upload.close()
        raise HTTPException(400, f"Select between 2 and {config.MAX_BATCH_FILES} papers.")
    declared_size = sum(upload.size or 0 for upload in files)
    if declared_size > config.MAX_BATCH_MB * 1024 * 1024:
        for upload in files:
            await upload.close()
        raise HTTPException(413, f"The paper bundle is larger than {config.MAX_BATCH_MB} MB.")
    if not _BATCH_SLOT.acquire(blocking=False):
        for upload in files:
            await upload.close()
        raise HTTPException(409, "A paper bundle is already being reviewed. Wait for it to finish first.")

    saved_paths = []
    batch = None
    try:
        jobs = []
        paths = []
        total_size = 0
        for upload in files:
            filename = _safe_filename(upload.filename or "paper")
            job = Job(filename, persist_result=True)
            job.status = "queued"
            try:
                filename, path, size = await _save_upload(upload)
            except HTTPException as exc:
                job.status = "error"
                job.error = exc.detail
                paths.append(None)
            else:
                total_size += size
                if total_size > config.MAX_BATCH_MB * 1024 * 1024:
                    os.remove(path)
                    raise HTTPException(413, f"The paper bundle is larger than {config.MAX_BATCH_MB} MB.")
                saved_paths.append(path)
                paths.append(path)
            jobs.append(job)

        _prune_batches()
        if len(BATCHES) >= MAX_RETAINED_BATCHES:
            raise HTTPException(409, "All saved bundle slots are in use. Try again after a bundle finishes.")
        batch = Batch(jobs)
        BATCHES[batch.id] = batch
        JOBS.update((job.id, job) for job in jobs)
        _prune_jobs()
        worker = threading.Thread(
            target=work_batch,
            args=(batch, paths, verify_online),
            daemon=True,
        )
        worker.start()
        return {"batch_id": batch.id}
    except Exception:
        if batch:
            BATCHES.pop(batch.id, None)
            for job in batch.jobs:
                _remove_job(job)
        for path in saved_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        _BATCH_SLOT.release()
        raise
    finally:
        for upload in files:
            await upload.close()


@app.get("/api/batches/{batch_id}")
def batch_status(batch_id: str):
    batch = BATCHES.get(batch_id)
    if not batch:
        raise HTTPException(404, "Unknown paper bundle.")
    active = next((job for job in batch.jobs if job.status in {"queued", "running"}), None)
    completed = sum(job.status in {"done", "error"} for job in batch.jobs)
    progress = sum(
        1.0 if job.status in {"done", "error"} else job.progress
        for job in batch.jobs
    ) / len(batch.jobs)
    return {
        "status": _batch_status(batch),
        "stage": active.stage if active else "done",
        "progress": round(progress, 3),
        "completed": completed,
        "total": len(batch.jobs),
        "log": active.log[-12:] if active else [],
        "items": [
            {
                "job_id": job.id,
                "name": job.name,
                "status": job.status,
                "progress": job.progress,
                "error": job.error,
            }
            for job in batch.jobs
        ],
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    return {"status": job.status, "stage": job.stage, "progress": job.progress, "log": job.log[-12:], "error": job.error}


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.status != "done":
        raise HTTPException(404, "Result not ready.")
    try:
        return _load_result(job)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        raise HTTPException(500, "The saved paper review could not be read.") from exc


@app.post("/api/jobs/{job_id}/ask")
def ask_about_paper(job_id: str, request: AskRequest):
    job = JOBS.get(job_id)
    if not job or job.status != "done":
        raise HTTPException(404, "Paper review not found. Upload and review the paper again.")
    question = request.question.strip()
    if not question:
        raise HTTPException(422, "Enter a question about the paper.")
    history = [item.dict() for item in request.history[-8:]]
    try:
        return questions.answer(_load_text(job), question, history)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, "The saved paper text could not be read.") from exc
