from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import platform
import queue
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .answering import AnswerService
from .config import get_settings
from .db import Repository
from .demo import generate_messages
from .importers import LineTxtImporter
from .inference import DeterministicStubProvider
from .inference.mac_local import MacLocalProvider
from .memory import MemoryExtractor
from .memory.local_plan import LocalPlanExtractor, is_backfill_candidate, time_window
from .profiler import PipelineProfiler


class ImportPayload(BaseModel):
    filename: str = "line-chat.txt"
    content: str


class CommitImportPayload(BaseModel):
    preview_id: str


class MessagePayload(BaseModel):
    sender: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=10000)
    timestamp: str | None = None


class QueryPayload(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


def create_app(database_path: str | Path | None = None, static_dir: str | Path | None = None) -> FastAPI:
    settings = get_settings(database_path)
    repo = Repository(settings.database_path)
    importer = LineTxtImporter(settings.default_timezone)
    extractor = MemoryExtractor()
    previews: dict[str, dict] = {}
    provider = MacLocalProvider(settings.local_model_base_url, settings.local_model_name) if settings.inference_provider == "mac_local" else DeterministicStubProvider()
    plan_extractor = LocalPlanExtractor(provider)
    plan_queue: queue.Queue[str] = queue.Queue()
    queued_plan_ids: set[str] = set()
    plan_queue_lock = threading.Lock()
    profiler = PipelineProfiler()
    capture_lock = threading.Lock()
    capture_state = {"process": None, "conversation_id": None, "state": "stopped", "frames": 0,
                     "uncertain": 0, "started_at": None, "window_label": None, "app_label": None}

    def consume_capture_output(process, conversation_id: str):
        for line in process.stdout:
            try: event = __import__("json").loads(line)
            except (ValueError, TypeError): continue
            kind = event.get("type")
            if kind == "state":
                capture_state["state"] = event.get("state", "unknown")
                capture_state["window_label"] = event.get("window_label", capture_state.get("window_label"))
                capture_state["app_label"] = event.get("app_label", capture_state.get("app_label"))
            elif kind == "error":
                capture_state["state"] = "error"
                capture_state["error"] = event.get("message", "capture_failed")
            elif kind == "frame":
                capture_state["frames"] += 1
                profiler.record("frame_to_ocr", 0)
                profiler.record("ocr", event.get("ocr_ms", 0), "ocr_frames")
                profiler.record("change_detection_dedup", event.get("change_detection_ms", 0))
                for _ in range(min(int(event.get("duplicates", 0)), 500)):
                    profiler.record("duplicate_observation", 0, "duplicates_dropped")
            elif kind == "message":
                if capture_state.get("state") in {"stopping", "stopped", "cancelled", "error"}:
                    continue
                profiler.record("capture_detection", 0)
                confidence = float(event.get("confidence", 0))
                if confidence < 0.70:
                    capture_state["uncertain"] += 1
                    profiler.record("ocr_uncertain", 0, "uncertain_detections")
                    continue
                started = time.monotonic()
                message = {"sender": "unknown", "timestamp": event.get("timestamp", datetime.now().astimezone().isoformat()),
                           "type": "text", "content": event.get("text", ""),
                           "source_locator": {"source_type": "live_capture", "capture_confidence": confidence,
                                              "speaker": "unknown", "timestamp_source": "capture_observation",
                                              "window_label": event.get("window_label"), "source_app_label": event.get("app_label")}}
                inserted, ids = repo.insert_messages(conversation_id, [message])
                profiler.record("capture_change_dedupe_ingest", (time.monotonic() - started) * 1000,
                                "new_text_detected" if inserted else "duplicates_dropped")
                if inserted:
                    observed = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")) if event.get("timestamp") else datetime.now().astimezone()
                    profiler.record("observed_to_searchable", (datetime.now().astimezone() - observed.astimezone()).total_seconds() * 1000)
                    profiler.record("ingestion_index", 0, "messages_ingested")
                    memory_started = time.monotonic()
                    analyze(conversation_id)
                    profiler.record("message_to_memory_update", (time.monotonic() - memory_started) * 1000)
        if capture_state.get("state") != "error": capture_state["state"] = "stopped"

    app = FastAPI(title="RecallSidecar API", version="0.1.0", docs_url="/api/docs", redoc_url=None)
    app.state.repo = repo
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"], allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    def ensure_conversation(conversation_id: str):
        conversation = repo.get_conversation(conversation_id)
        if not conversation: raise HTTPException(404, "conversation_not_found")
        return conversation

    def analyze(conversation_id: str):
        started = time.monotonic()
        messages = repo.messages(conversation_id, limit=100000)
        facts, commitments = extractor.analyze(messages)
        repo.replace_analysis(conversation_id, facts, commitments)
        profiler.record("memory_extraction", (time.monotonic() - started) * 1000)
        return {"memory_count": len(facts), "commitment_count": len(commitments)}

    def extract_plan(message_id: str, cache: dict | None = None):
        message = repo.message(message_id)
        if not message:
            return
        key = (message["sender"], message["content"])
        started = time.monotonic()
        try:
            if cache is not None and key in cache:
                plan = cache[key]
                if plan and plan["time_expression"]:
                    observed = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
                    interval = time_window(plan["time_expression"], observed)
                    plan = {**plan, "start_date": interval[0] if interval else None,
                            "end_date": interval[1] if interval else None}
            else:
                plan = plan_extractor.extract(message)
                if cache is not None:
                    cache[key] = plan
            repo.save_plan_extraction(message, settings.local_model_name, plan)
            profiler.record("model_plan_extraction", (time.monotonic() - started) * 1000)
        except Exception:
            # Ollama may be offline. Leave the message pending for a later restart/reindex.
            pass

    def schedule_plan_backfill():
        if not getattr(provider, "supports_generation", False):
            return
        for message in repo.pending_plan_messages(settings.local_model_name):
            if not is_backfill_candidate(message["content"]):
                continue
            with plan_queue_lock:
                if message["id"] in queued_plan_ids:
                    continue
                queued_plan_ids.add(message["id"])
            plan_queue.put(message["id"])

    def plan_worker():
        cache: dict[tuple[str, str], dict | None] = {}
        while True:
            message_id = plan_queue.get()
            try:
                extract_plan(message_id, cache)
            finally:
                with plan_queue_lock:
                    queued_plan_ids.discard(message_id)
                plan_queue.task_done()

    if getattr(provider, "supports_generation", False):
        threading.Thread(target=plan_worker, name="local-plan-extraction", daemon=True).start()
        schedule_plan_backfill()

    @app.get("/api/health")
    def health(): return {"status": "ok"}

    @app.post("/api/demo/seed")
    def seed_demo():
        existing = repo.get_conversation("demo-alice")
        if existing:
            return {"conversation_id": existing["id"], "inserted": 0, "message_count": existing["message_count"], "deduplicated": True}
        cid = repo.create_conversation("Alice 與小宇", "synthetic_demo", "synthetic-line-chat.txt", settings.default_timezone, "demo-alice")
        inserted, _ = repo.insert_messages(cid, generate_messages())
        detail = analyze(cid)
        schedule_plan_backfill()
        return {"conversation_id": cid, "inserted": inserted, "message_count": inserted, **detail}

    @app.post("/api/imports/line/preview")
    async def preview_line(payload: ImportPayload, request: Request):
        size = len(payload.content.encode("utf-8"))
        if size > settings.max_import_bytes: raise HTTPException(413, "file_too_large")
        parsed = importer.parse(payload.content, payload.filename)
        preview_id = f"preview-{uuid.uuid4()}"
        previews[preview_id] = parsed
        return {"preview_id": preview_id, "title": parsed["title"], "source_filename": parsed["source_filename"],
                "message_count": len(parsed["messages"]) + len(parsed.get("unknown_messages", [])),
                "valid_message_count": len(parsed["messages"]), "unknown_count": len(parsed.get("unknown_messages", [])),
                "participants": parsed["participants"], "date_start": parsed["date_start"],
                "date_end": parsed["date_end"], "rejected_count": len(parsed["rejected"]), "rejected": parsed["rejected"][:30],
                "warnings": parsed["warnings"], "sample_messages": parsed["messages"][:10]}

    @app.post("/api/imports/line/commit")
    def commit_line(payload: CommitImportPayload):
        parsed = previews.pop(payload.preview_id, None)
        if not parsed: raise HTTPException(404, "preview_not_found_or_expired")
        if not parsed["messages"] and not parsed.get("unknown_messages"): raise HTTPException(422, "no_messages_to_import")
        existing = repo.find_import_conversation(parsed["title"], parsed["source_filename"])
        cid = existing["id"] if existing else repo.create_conversation(parsed["title"], "line_txt", parsed["source_filename"], parsed["timezone"])
        inserted, _ = repo.insert_messages(cid, parsed["messages"] + parsed.get("unknown_messages", []))
        detail = analyze(cid)
        schedule_plan_backfill()
        jid = repo.create_job("line_import", detail={"conversation_id": cid, "inserted": inserted, **detail})
        return {"job_id": jid, "conversation_id": cid, "inserted": inserted, "deduplicated": bool(existing and inserted == 0), **detail}

    @app.get("/api/imports/{job_id}")
    def import_job(job_id: str):
        if not (job := repo.job(job_id)): raise HTTPException(404, "job_not_found")
        return job

    @app.get("/api/conversations")
    def conversations(): return repo.list_conversations()

    @app.get("/api/conversations/{conversation_id}")
    def conversation(conversation_id: str): return ensure_conversation(conversation_id)

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str):
        if capture_state.get("conversation_id") == conversation_id and capture_state.get("process") and capture_state["process"].poll() is None:
            capture_state["state"] = "stopping"
            capture_state["process"].stdin.write("stop\n"); capture_state["process"].stdin.flush()
        if not repo.delete_conversation(conversation_id): raise HTTPException(404, "conversation_not_found")
        return {"deleted": True}

    @app.get("/api/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, limit: int = 100, before: str | None = None, around: str | None = None):
        ensure_conversation(conversation_id)
        return repo.messages(conversation_id, min(max(limit, 1), 500), before, around)

    @app.post("/api/conversations/{conversation_id}/messages")
    def add_message(conversation_id: str, payload: MessagePayload):
        ensure_conversation(conversation_id)
        message = {"sender": payload.sender, "content": payload.content, "timestamp": payload.timestamp or datetime.now().astimezone().isoformat(),
                   "type": "text", "source_locator": {"type": "demo_chat"}}
        started = time.monotonic()
        inserted, ids = repo.insert_messages(conversation_id, [message])
        if not inserted:
            profiler.record("dedupe", (time.monotonic() - started) * 1000, "duplicates_dropped")
            raise HTTPException(409, "duplicate_message")
        profiler.record("ingestion_index", (time.monotonic() - started) * 1000, "messages_ingested")
        detail = analyze(conversation_id)
        if getattr(provider, "supports_generation", False) and is_backfill_candidate(payload.content):
            extract_plan(ids[0])
        return {"message": repo.message(ids[0]), **detail}

    @app.post("/api/conversations/{conversation_id}/index")
    def index_conversation(conversation_id: str):
        ensure_conversation(conversation_id)
        detail = analyze(conversation_id)
        schedule_plan_backfill()
        jid = repo.create_job("index", detail={"conversation_id": conversation_id, **detail})
        return {"job_id": jid, **detail}

    @app.get("/api/conversations/{conversation_id}/memories")
    def memories(conversation_id: str):
        ensure_conversation(conversation_id);return repo.facts(conversation_id)

    @app.get("/api/conversations/{conversation_id}/plans")
    def plans(conversation_id: str):
        ensure_conversation(conversation_id)
        return repo.inferred_plans(conversation_id, limit=100)

    @app.get("/api/conversations/{conversation_id}/changes")
    def changes(conversation_id: str):
        ensure_conversation(conversation_id)
        groups: dict[str, list[dict]] = {}
        for fact in repo.facts(conversation_id): groups.setdefault(f'{fact["subject"]}|{fact["category"]}', []).append(fact)
        return [{"subject": values[0]["subject"], "category": values[0]["category"], "history": values}
                for values in groups.values() if len(values) > 1]

    @app.get("/api/conversations/{conversation_id}/commitments")
    def commitments(conversation_id: str):
        ensure_conversation(conversation_id)
        result=[]
        for item in repo.commitments(conversation_id):
            item["source_message"] = repo.message(item["source_message_id"])
            item["completed_message"] = repo.message(item["completed_message_id"]) if item.get("completed_message_id") else None
            result.append(item)
        return result

    @app.post("/api/conversations/{conversation_id}/query")
    def query(conversation_id: str, payload: QueryPayload):
        ensure_conversation(conversation_id)
        started = time.monotonic()
        result = AnswerService(repo, provider).answer(conversation_id, payload.question)
        profiler.record("retrieval_answer", (time.monotonic() - started) * 1000)
        return result

    @app.get("/api/system/status")
    def system_status():
        return {**repo.system_counts(), "provider": provider.healthcheck(), "local_only": True,
                "database_path": str(settings.database_path.resolve()), "database_encrypted": False,
                "network_claim": "Core query flow requires no network. Dependency and model installation are separate.",
                "ugen300_benchmark": "TBD - measure on hardware"}

    @app.get("/api/system/profiler")
    def profiler_status():
        process = capture_state["process"]
        if process and process.poll() is not None and capture_state["state"] not in {"error", "cancelled"}:
            capture_state["state"] = "stopped"
        capture = {"status": capture_state["state"], "conversation_id": capture_state["conversation_id"],
                                  "frames_observed": capture_state["frames"], "uncertain_detections": capture_state["uncertain"],
                                  "started_at": capture_state["started_at"], "window_label": capture_state.get("window_label"),
                                  "app_label": capture_state.get("app_label"), "error": capture_state.get("error"),
                                  "provider": provider.healthcheck(), "ocr_provider": "Apple Vision" if platform.system() == "Darwin" else "unavailable",
                                  "accelerator": "Not available"}
        return profiler.snapshot(capture)

    @app.post("/api/system/capture/start")
    def capture_start():
        if platform.system() != "Darwin": raise HTTPException(501, "live_capture_requires_macos")
        with capture_lock:
            if capture_state["process"] and capture_state["process"].poll() is None:
                raise HTTPException(409, "capture_already_running")
            script = Path(__file__).with_name("live_capture.swift")
            cid = repo.create_conversation("Live Capture Session", "live_capture", None, settings.default_timezone)
            capture_state.update({"conversation_id": cid, "state": "starting", "frames": 0, "uncertain": 0,
                                  "started_at": datetime.now().astimezone().isoformat(), "window_label": None,
                                  "app_label": None, "error": None})
            try:
                process = subprocess.Popen(["swift", str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, text=True, bufsize=1)
            except OSError as exc:
                capture_state["state"] = "error"
                raise HTTPException(503, f"swift_helper_unavailable: {exc}")
            capture_state["process"] = process
            threading.Thread(target=consume_capture_output, args=(process, cid), daemon=True).start()
            return {"status": "selecting_window", "conversation_id": cid}

    @app.post("/api/system/capture/{action}")
    def capture_action(action: str):
        if action not in {"pause", "resume", "stop"}: raise HTTPException(404, "unknown_capture_action")
        process = capture_state["process"]
        if not process or process.poll() is not None: raise HTTPException(409, "capture_not_running")
        process.stdin.write(action + "\n"); process.stdin.flush()
        if action == "pause": capture_state["state"] = "paused"
        if action == "resume": capture_state["state"] = "capturing"
        if action == "stop": capture_state["state"] = "stopping"
        return {"status": capture_state["state"]}

    @app.post("/api/system/profiler/reset")
    def profiler_reset():
        profiler.reset(); capture_state["frames"] = 0; capture_state["uncertain"] = 0
        return {"reset": True}

    @app.post("/api/system/profiler/pause")
    def profiler_pause(payload: dict):
        with profiler._lock: profiler.paused = bool(payload.get("paused"))
        return {"sampling_paused": profiler.paused}

    @app.delete("/api/system/data")
    def delete_all_data():
        process = capture_state.get("process")
        if process and process.poll() is None:
            process.stdin.write("stop\n"); process.stdin.flush()
        capture_state["state"] = "stopping"
        repo.delete_all();return {"deleted": True}

    root = Path(static_dir) if static_dir else Path(__file__).resolve().parents[2] / "dist"
    if root.exists():
        app.mount("/assets", StaticFiles(directory=root), name="assets")
        @app.get("/")
        def index(): return FileResponse(root / "index.html")
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            file = root / path
            return FileResponse(file if file.is_file() else root / "index.html")
    return app


app = create_app()
