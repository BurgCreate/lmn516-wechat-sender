"""Local one-shot scheduler. Invoke run-due from the logged-in macOS user session."""
import datetime as dt
import fcntl
import json
import os
import uuid
from pathlib import Path
from . import DATA_DIR, digest_text, send_message

JOBS = DATA_DIR / "jobs.json"


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        os.chmod(tmp, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(tmp), str(path))


def _job_lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (DATA_DIR / "schedule.lock").open("a")
    os.chmod(DATA_DIR / "schedule.lock", 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    return lock


def schedule_once(contact, message, at=None, after_minutes=None, source_sha256=None):
    if not contact.strip() or not message:
        raise ValueError("contact and text are required")
    content_sha = digest_text(message)
    if source_sha256 and source_sha256.lower() != content_sha:
        raise ValueError("source-sha256-mismatch")
    if at:
        due = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
        if due.tzinfo is None or due.utcoffset() is None:
            raise ValueError("--at needs explicit timezone")
    elif after_minutes is not None and after_minutes > 0:
        due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=after_minutes)
    else:
        raise ValueError("provide --at or positive --after-minutes")
    if due <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("due time must be in future")
    lock = _job_lock()
    try:
        jobs = _load(JOBS, [])
        job = {"id": uuid.uuid4().hex[:12], "contact": contact, "text": message,
               "content_sha256": content_sha, "due_at": due.isoformat(), "status": "pending"}
        jobs.append(job)
        _save(JOBS, jobs)
    finally:
        lock.close()
    return {"ok": True, "job": {key: value for key, value in job.items() if key != "text"}}


def list_jobs():
    lock = _job_lock()
    try:
        jobs = _load(JOBS, [])
    finally:
        lock.close()
    return {"ok": True, "jobs": [
        {key: value for key, value in j.items() if key != "text"} for j in jobs
    ]}


def cancel_job(job_id):
    lock = _job_lock()
    try:
        jobs = _load(JOBS, [])
        for job in jobs:
            if job["id"] == job_id and job["status"] == "pending":
                job["status"] = "cancelled"
                _save(JOBS, jobs)
                return {"ok": True, "cancelled": job_id}
        return {"ok": False, "error": "pending-job-not-found"}
    finally:
        lock.close()


def run_due(dry_run=False, app_path=None):
    lock = _job_lock()
    try:
        jobs = _load(JOBS, [])
        now = dt.datetime.now(dt.timezone.utc)
        completed = []
        for job in jobs:
            if job["status"] != "pending":
                continue
            if dt.datetime.fromisoformat(job["due_at"]) > now:
                continue
            if dry_run:
                completed.append({"id": job["id"], "status": "due-dry-run"})
                continue
            # Persist claim BEFORE GUI interaction; never retry an ambiguous send.
            job["status"] = "claimed-no-auto-retry"
            _save(JOBS, jobs)
            try:
                result = send_message(job["contact"], job["text"],
                                      source_sha256=job["content_sha256"],
                                      app_path=app_path)
                job["status"] = result["delivery_state"]
                job["attempted"] = result["attempted"]
            except Exception as exc:
                job["status"] = "ambiguous-do-not-resend"
                job["error_type"] = type(exc).__name__
            _save(JOBS, jobs)
            completed.append({"id": job["id"], "status": job["status"]})
        return {"ok": True, "due": completed}
    finally:
        lock.close()
