"""FastAPI entry point for the WAHA Deleted Message Notifier."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.admin.auth import AdminNotAuthenticated
from app.admin.router import _limiter, router as admin_router
from app import database as db
from app.config import settings
from app.handlers.any_event import handle_any
from app.handlers.revoke_event import handle_revoke
from app.tasks.cleanup import run_cleanup
from app.waha.client import WAHAClient

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        structlog.processors.JSONRenderer(),
    ],
)
logger = structlog.get_logger(__name__)

# ------------------------------------------------------------------
# Global shared resources
# ------------------------------------------------------------------
waha_client: WAHAClient | None = None
scheduler: AsyncIOScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global waha_client, scheduler

    logger.info("starting up", base_url=settings.waha_base_url)
    await db.init_db()

    waha_client = WAHAClient()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_cleanup, "interval", hours=6, id="cleanup")
    scheduler.start()
    logger.info("scheduler started")

    yield

    scheduler.shutdown(wait=False)
    if waha_client:
        await waha_client.aclose()
    logger.info("shutdown complete")


# ------------------------------------------------------------------
# App
# ------------------------------------------------------------------
app = FastAPI(
    title="WAHA Deleted Message Notifier",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = _limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(AdminNotAuthenticated)
async def admin_not_authenticated_handler(request: Request, exc: AdminNotAuthenticated):
    return RedirectResponse(url="/admin/login", status_code=302)


app.include_router(admin_router)


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok"}


# ------------------------------------------------------------------
# Internal status — consumed by the shared Admin Panel in bot-reminder
# ------------------------------------------------------------------
@app.get("/internal/status", tags=["meta"])
async def internal_status() -> dict:
    """Return key metrics for the admin panel in bot-reminder."""
    from pathlib import Path

    import aiosqlite

    result: dict[str, Any] = {
        "db_ok": False,
        "messages_total": 0,
        "messages_with_media": 0,
        "messages_last_24h": 0,
        "archived_chats": 0,
        "media_dir_exists": Path(settings.media_dir).exists(),
        "media_files_count": 0,
        "media_size_bytes": 0,
    }

    try:
        since_24h = int(time.time()) - 86400
        async with aiosqlite.connect(settings.db_path) as conn:
            async with conn.execute("SELECT COUNT(*) FROM messages") as cur:
                result["messages_total"] = (await cur.fetchone())[0]
            async with conn.execute(
                "SELECT COUNT(*) FROM messages WHERE has_media = 1"
            ) as cur:
                result["messages_with_media"] = (await cur.fetchone())[0]
            async with conn.execute(
                "SELECT COUNT(*) FROM messages WHERE created_at >= ?", (since_24h,)
            ) as cur:
                result["messages_last_24h"] = (await cur.fetchone())[0]
            async with conn.execute(
                "SELECT COUNT(*) FROM archived_chats WHERE is_archived = 1"
            ) as cur:
                result["archived_chats"] = (await cur.fetchone())[0]
        result["db_ok"] = True
    except Exception as exc:
        result["db_error"] = str(exc)

    try:
        media_path = Path(settings.media_dir)
        if media_path.exists():
            files = list(media_path.rglob("*"))
            result["media_files_count"] = sum(1 for f in files if f.is_file())
            result["media_size_bytes"] = sum(
                f.stat().st_size for f in files if f.is_file()
            )
    except Exception:
        pass

    return result


# ------------------------------------------------------------------
# Incident log — consumed by the shared Admin Panel in bot-reminder
# ------------------------------------------------------------------

class IncidentCreate(BaseModel):
    incident_type: str
    message_id: Optional[str] = None
    chat_id: Optional[str] = None
    sender_jid: Optional[str] = None
    notification_text: Optional[str] = None
    error_detail: Optional[str] = None


class NoteBody(BaseModel):
    note: Optional[str] = None


class ReorderBody(BaseModel):
    ids: list[str]


@app.get("/internal/incidents", tags=["meta"])
async def list_incidents(status_filter: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Return incident rows ordered by priority ASC, occurred_at DESC."""
    return await db.list_incidents(status=status_filter, limit=limit)


@app.post("/internal/incidents", tags=["meta"])
async def create_incident_api(body: IncidentCreate) -> dict:
    """Create an incident (used by bot-reminder for thumbs-down in notify group)."""
    incident_id = await db.create_incident(
        incident_type=body.incident_type,
        message_id=body.message_id,
        chat_id=body.chat_id,
        sender_jid=body.sender_jid,
        notification_text=body.notification_text,
        error_detail=body.error_detail,
    )
    return {"id": incident_id}


@app.post("/internal/incidents/reorder", tags=["meta"])
async def reorder_incidents(body: ReorderBody) -> dict:
    await db.reorder_incidents(body.ids)
    return {"ok": True}


@app.post("/internal/incidents/{incident_id}/resolve", tags=["meta"])
async def resolve_incident(incident_id: str) -> dict:
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "resolved", int(time.time()))
    return {"ok": True}


@app.post("/internal/incidents/{incident_id}/unresolve", tags=["meta"])
async def unresolve_incident(incident_id: str) -> dict:
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "open")
    return {"ok": True}


@app.post("/internal/incidents/{incident_id}/ignore", tags=["meta"])
async def ignore_incident(incident_id: str) -> dict:
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "ignored", int(time.time()))
    return {"ok": True}


@app.post("/internal/incidents/{incident_id}/note", tags=["meta"])
async def note_incident(incident_id: str, body: NoteBody) -> dict:
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_note(incident_id, body.note)
    return {"ok": True}


# ------------------------------------------------------------------
# Runtime settings
# ------------------------------------------------------------------

@app.get("/internal/settings", tags=["meta"])
async def get_settings() -> dict:
    notify_archived = await db.get_setting("notify_archived", "true")
    return {"notify_archived": notify_archived.lower() == "true"}


@app.post("/internal/settings/notify_archived", tags=["meta"])
async def toggle_notify_archived() -> dict:
    current = await db.get_setting("notify_archived", "true")
    new_val = "false" if current.lower() == "true" else "true"
    await db.set_setting("notify_archived", new_val)
    return {"notify_archived": new_val == "true"}


# ------------------------------------------------------------------
# Webhook
# ------------------------------------------------------------------
@app.post("/webhook/waha", status_code=status.HTTP_200_OK, tags=["webhook"])
async def waha_webhook(request: Request) -> JSONResponse:
    """Receive WAHA webhook events.

    Expected to handle:
    - message.any   → capture media / metadata
    - message.revoked → notify about deletion
    - chat.archive   → track archived status locally
    """
    try:
        event: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_type: str = event.get("event", "")
    event_id: str = event.get("id", "")

    log = logger.bind(event=event_type, event_id=event_id)
    log.info("webhook received", payload=event)

    # ------------------------------------------------------------------
    # Idempotency – skip already-processed events
    # ------------------------------------------------------------------
    if settings.webhook_dedup_enabled and event_id:
        if await db.is_event_processed(event_id):
            log.info("duplicate event, skipping")
            return JSONResponse({"status": "duplicate"})
        await db.mark_event_processed(event_id)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    try:
        if event_type == "message.any":
            await handle_any(event, waha_client)

        elif event_type == "message.revoked":
            await handle_revoke(event, waha_client)

        elif event_type == "chat.archive":
            payload = event.get("payload") or {}
            chat_id = payload.get("id") or ""
            archived = bool(payload.get("archived"))
            if chat_id:
                await db.set_chat_archived(chat_id, archived)
                log.info("chat archive updated", chat_id=chat_id, archived=archived)

        else:
            log.debug("unhandled event type, ignoring")

    except Exception as exc:
        log.error("handler error", error=str(exc), exc_info=True)
        # Return 200 anyway so WAHA doesn't keep retrying
        return JSONResponse({"status": "error", "detail": str(exc)})

    return JSONResponse({"status": "ok"})
