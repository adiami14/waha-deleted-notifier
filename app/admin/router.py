"""
Notify Delete admin panel routes.

Direct DB access — no HTTP calls to other services.
All mutations follow POST-redirect-GET. Flash messages via short-lived signed cookie.
"""

from __future__ import annotations

import datetime
import time
from pathlib import Path

import aiosqlite
import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.admin.auth import (
    COOKIE_NAME,
    AdminNotAuthenticated,
    clear_session_cookie,
    create_session_cookie,
    require_admin,
    verify_password,
)
from app.config import settings
from app import database as db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])
_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_limiter = Limiter(key_func=get_remote_address)

_FLASH_COOKIE = "nd_admin_flash"


# ---------------------------------------------------------------------------
# Flash helpers
# ---------------------------------------------------------------------------

def _flash_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.secret_key.get_secret_value(), salt="nd-flash")


def _set_flash(response, message: str, kind: str = "success") -> None:
    token = _flash_serializer().dumps({"m": message, "k": kind})
    response.set_cookie(_FLASH_COOKIE, token, max_age=30, httponly=True, samesite="strict")


def _read_flash(request: Request, response) -> dict | None:
    token = request.cookies.get(_FLASH_COOKIE)
    if not token:
        return None
    try:
        data = _flash_serializer().loads(token)
        response.delete_cookie(_FLASH_COOKIE)
        return data
    except Exception:
        return None


def _redirect(path: str, message: str = "", kind: str = "success") -> RedirectResponse:
    resp = RedirectResponse(url=path, status_code=302)
    if message:
        _set_flash(resp, message, kind)
    return resp


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    return _templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
@_limiter.limit("5/minute")
async def post_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not settings.admin_password_hash:
        raise HTTPException(status_code=503, detail="Admin panel not configured.")
    if username == settings.admin_username and verify_password(password):
        resp = RedirectResponse(url="/admin/dashboard", status_code=302)
        create_session_cookie(resp, username)
        logger.info("nd_admin.login_success")
        return resp
    logger.warning("nd_admin.login_failed")
    return _templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "שם משתמש או סיסמה שגויים."},
        status_code=401,
    )


@router.post("/logout")
async def post_logout(_: str = Depends(require_admin)):
    resp = RedirectResponse(url="/admin/login", status_code=302)
    clear_session_cookie(resp)
    return resp


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(
    request: Request,
    _: str = Depends(require_admin),
):
    status_data: dict | None = None
    error: str | None = None
    since_24h = int(time.time()) - 86400

    try:
        result: dict = {
            "db_ok": False,
            "messages_total": 0,
            "messages_with_media": 0,
            "messages_last_24h": 0,
            "archived_chats": 0,
            "media_dir_exists": Path(settings.media_dir).exists(),
            "media_files_count": 0,
            "media_size_bytes": 0,
        }
        async with aiosqlite.connect(settings.db_path) as conn:
            async with conn.execute("SELECT COUNT(*) FROM messages") as cur:
                result["messages_total"] = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM messages WHERE has_media = 1") as cur:
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

        media_path = Path(settings.media_dir)
        if media_path.exists():
            files = list(media_path.rglob("*"))
            result["media_files_count"] = sum(1 for f in files if f.is_file())
            result["media_size_bytes"] = sum(f.stat().st_size for f in files if f.is_file())

        status_data = result
    except Exception as exc:
        error = str(exc)

    nd_settings = {
        "notify_archived": (await db.get_setting("notify_archived", "true")).lower() == "true"
    }

    resp = _templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "status": status_data,
            "nd_settings": nd_settings,
            "error": error,
            "flash": None,
        },
    )
    flash = _read_flash(request, resp)
    resp.context["flash"] = flash  # type: ignore[attr-defined]
    return resp


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.post("/settings/toggle-archived")
async def toggle_archived(_: str = Depends(require_admin)):
    current = await db.get_setting("notify_archived", "true")
    new_val = "false" if current.lower() == "true" else "true"
    await db.set_setting("notify_archived", new_val)
    return _redirect("/admin/dashboard", "הגדרה עודכנה.", "success")


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@router.get("/incidents", response_class=HTMLResponse)
async def get_incidents(
    request: Request,
    status: str = "",
    _: str = Depends(require_admin),
):
    rows = await db.list_incidents(status=status or None, limit=200)

    # Format timestamps from Unix epoch to readable string
    for row in rows:
        ts = row.get("occurred_at")
        if ts and isinstance(ts, int):
            row["occurred_at"] = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    resp = _templates.TemplateResponse(
        "incidents.html",
        {
            "request": request,
            "rows": rows,
            "error": None,
            "filter_status": status,
            "flash": None,
        },
    )
    flash = _read_flash(request, resp)
    resp.context["flash"] = flash  # type: ignore[attr-defined]
    return resp


@router.post("/incidents/reorder")
async def post_reorder_incidents(
    request: Request,
    _: str = Depends(require_admin),
):
    body = await request.json()
    ids = body.get("ids", [])
    if ids:
        await db.reorder_incidents(ids)
    return {"ok": True}


@router.post("/incidents/{incident_id}/resolve")
async def post_resolve_incident(
    incident_id: str,
    note: str = Form(""),
    _: str = Depends(require_admin),
):
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "resolved", int(time.time()))
    if note:
        await db.update_incident_note(incident_id, note)
    return _redirect("/admin/incidents", "האירוע סומן כ-resolved.", "success")


@router.post("/incidents/{incident_id}/ignore")
async def post_ignore_incident(
    incident_id: str,
    note: str = Form(""),
    _: str = Depends(require_admin),
):
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "ignored", int(time.time()))
    if note:
        await db.update_incident_note(incident_id, note)
    return _redirect("/admin/incidents", "האירוע סומן כ-ignored.", "success")


@router.post("/incidents/{incident_id}/unresolve")
async def post_unresolve_incident(
    incident_id: str,
    _: str = Depends(require_admin),
):
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_status(incident_id, "open")
    return _redirect("/admin/incidents", "האירוע הוחזר לסטטוס open.", "success")


@router.post("/incidents/{incident_id}/note")
async def post_incident_note(
    incident_id: str,
    note: str = Form(""),
    _: str = Depends(require_admin),
):
    inc = await db.get_incident(incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await db.update_incident_note(incident_id, note or None)
    return _redirect("/admin/incidents", "ההערה נשמרה.", "success")
