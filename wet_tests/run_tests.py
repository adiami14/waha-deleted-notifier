#!/usr/bin/env python3
"""
Wet-test runner: sends text, image, and voice messages to all 5 test
destinations (4 groups + 1 private chat), then deletes them all in order.

Message tags embedded in content:
  WET-TEXT-01 .. WET-TEXT-05
  WET-IMG-01  .. WET-IMG-05
  WET-VOICE-01 .. WET-VOICE-05  (visible in logs only — voice has no caption)

Run after setup_groups.py.
"""
import base64
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / ".env")

BASE_URL  = os.environ.get("WAHA_BASE_URL", "http://localhost:3000")
API_KEY   = os.environ["WAHA_API_KEY"]

ASSETS_DIR     = Path(__file__).parent / "assets"
STATE_FILE     = Path(__file__).parent / "state.json"
MESSAGES_FILE  = Path(__file__).parent / "messages.json"

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"X-Api-Key": API_KEY},
        timeout=60.0,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if not STATE_FILE.exists():
        raise FileNotFoundError(
            "state.json not found — run setup_groups.py first."
        )
    return json.loads(STATE_FILE.read_text())


def read_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def extract_api_id(resp: dict) -> str:
    """Pull the message ID from a WAHA send-response (best-effort)."""
    return (
        resp.get("id")
        or resp.get("key", {}).get("id")
        or ""
    )

# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

def send_text(
    client: httpx.Client,
    session: str,
    chat_id: str,
    msg_id: str,
    label: str,
) -> dict:
    """POST /api/sendText"""
    r = client.post(
        "/api/sendText",
        json={
            "session": session,
            "chatId":  chat_id,
            "text":    f"[{msg_id}] Wet-test text — {label}",
        },
    )
    r.raise_for_status()
    return r.json()


def send_image(
    client: httpx.Client,
    session: str,
    chat_id: str,
    msg_id: str,
    label: str,
) -> dict:
    """POST /api/sendImage  (base64 PNG)"""
    r = client.post(
        "/api/sendImage",
        json={
            "session": session,
            "chatId":  chat_id,
            "caption": f"[{msg_id}] Wet-test image — {label}",
            "file": {
                "mimetype": "image/png",
                "filename": "test_image.png",
                "data":     read_b64(ASSETS_DIR / "test_image.png"),
            },
        },
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def send_voice(
    client: httpx.Client,
    session: str,
    chat_id: str,
) -> dict:
    """POST /api/sendVoice  (base64 WAV with server-side ffmpeg conversion)"""
    r = client.post(
        "/api/sendVoice",
        json={
            "session": session,
            "chatId":  chat_id,
            "convert": True,
            "file": {
                "mimetype": "audio/wav",
                "filename": "test_voice.wav",
                "data":     read_b64(ASSETS_DIR / "test_voice.wav"),
            },
        },
    )
    r.raise_for_status()
    return r.json() if r.content else {}

# ---------------------------------------------------------------------------
# Delete helper
# ---------------------------------------------------------------------------

def delete_message(
    client: httpx.Client,
    session: str,
    chat_id: str,
    api_id: str,
) -> None:
    """DELETE /api/{session}/chats/{chatId}/messages/{messageId}"""
    r = client.delete(f"/api/{session}/chats/{chat_id}/messages/{api_id}")
    if r.status_code not in (200, 201, 204):
        print(f"  WARNING: delete returned HTTP {r.status_code}  ({api_id})")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    state   = load_state()
    session = state["sender_session"]

    both   = state["groups"]["both_archived"]    # [gid1, gid2]
    sonly  = state["groups"]["sender_archived"]  # [gid3, gid4]
    priv   = state["private_chat"]

    # Ordered list of (chat_id, human-readable label)
    destinations = [
        (both[0],  "BothArchived-1"),
        (both[1],  "BothArchived-2"),
        (sonly[0], "SenderArchived-1"),
        (sonly[1], "SenderArchived-2"),
        (priv,     "Private"),
    ]

    # Accumulates every sent message so we can delete them afterwards
    sent: list[dict] = []

    print("=== Wet Test Runner ===\n")
    print(f"Session    : {session}")
    print(f"Targets    : {len(destinations)} chats")
    print(f"Messages   : {len(destinations) * 3} total  "
          f"({len(destinations)} text + {len(destinations)} image + {len(destinations)} voice)\n")

    with make_client() as client:

        # ── Send phase ────────────────────────────────────────────────────
        print("─" * 50)
        print("SEND PHASE")
        print("─" * 50)

        for idx, (chat_id, label) in enumerate(destinations, start=1):
            seq = f"{idx:02d}"
            print(f"\n[{seq}] {label}  ({chat_id})")

            # Text
            text_id = f"WET-TEXT-{seq}"
            resp    = send_text(client, session, chat_id, text_id, label)
            api_id  = extract_api_id(resp)
            sent.append({"msg_id": text_id, "chat_id": chat_id, "api_id": api_id, "type": "text"})
            print(f"  text   {text_id}   api_id={api_id or '(none)'}")

            # Image
            img_id = f"WET-IMG-{seq}"
            resp   = send_image(client, session, chat_id, img_id, label)
            api_id = extract_api_id(resp)
            sent.append({"msg_id": img_id, "chat_id": chat_id, "api_id": api_id, "type": "image"})
            print(f"  image  {img_id}    api_id={api_id or '(none)'}")

            # Voice  (no caption — ID tracked in logs only)
            voice_id = f"WET-VOICE-{seq}"
            resp     = send_voice(client, session, chat_id)
            api_id   = extract_api_id(resp)
            sent.append({"msg_id": voice_id, "chat_id": chat_id, "api_id": api_id, "type": "voice"})
            print(f"  voice  {voice_id}  api_id={api_id or '(none)'}")

        # Save the full sent log so it survives a Ctrl-C
        MESSAGES_FILE.write_text(json.dumps(sent, indent=2))
        print(f"\nAll messages logged  ->  {MESSAGES_FILE}")

        # ── Pause ─────────────────────────────────────────────────────────
        print()
        try:
            input("Verify messages on the phone, then press ENTER to delete "
                  "them all (Ctrl-C to abort)...\n")
        except KeyboardInterrupt:
            print("\nAborted. Messages have NOT been deleted.")
            print(f"Run again or delete manually using {MESSAGES_FILE}.")
            return

        # ── Delete phase ──────────────────────────────────────────────────
        print("─" * 50)
        print("DELETE PHASE")
        print("─" * 50 + "\n")

        for entry in sent:
            msg_id  = entry["msg_id"]
            chat_id = entry["chat_id"]
            api_id  = entry["api_id"]

            if not api_id:
                print(f"  SKIP  {msg_id}  — no api_id was recorded")
                continue

            delete_message(client, session, chat_id, api_id)
            print(f"  deleted  {msg_id}  ({api_id})")

    print("\nDone — all messages deleted.")


if __name__ == "__main__":
    main()
