#!/usr/bin/env python3
"""
Wet-test setup: create 4 WhatsApp groups from the yarden session and archive
them according to the test scenarios.

Scenario A (both archived): groups 1 & 2 — archived from yarden AND adiami
Scenario B (yarden only):   groups 3 & 4 — archived from yarden ONLY

Also creates assets/test_image.png and assets/test_voice.wav used by run_tests.py.
Saves group IDs to state.json.

Run once before run_tests.py.
"""
import io
import json
import os
import struct
import time
import wave
import zlib
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / ".env")

BASE_URL       = os.environ.get("WAHA_BASE_URL", "http://localhost:3000")
API_KEY        = os.environ["WAHA_API_KEY"]
SENDER_SESSION  = os.environ.get("WET_TEST_SENDER_SESSION", "sender")
ADIAMI_SESSION  = os.environ.get("WAHA_LISTEN_SESSION", "listener")
ADIAMI_JID      = os.environ.get("WET_TEST_LISTENER_JID", "972500000000@c.us")

ASSETS_DIR = Path(__file__).parent / "assets"
STATE_FILE = Path(__file__).parent / "state.json"

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"X-Api-Key": API_KEY},
        timeout=30.0,
    )

# ---------------------------------------------------------------------------
# WAHA helpers
# ---------------------------------------------------------------------------

def create_group(client: httpx.Client, session: str, name: str) -> str:
    """POST /api/{session}/groups  →  returns group JID (e.g. 120363...@g.us)."""
    r = client.post(
        f"/api/{session}/groups",
        json={
            "name": name,
            "participants": [{"id": ADIAMI_JID}],
        },
    )
    r.raise_for_status()
    data = r.json()
    # WAHA returns group JID under different keys depending on engine version
    group_id = (
        data.get("JID")                               # NOWEB engine
        or data.get("id")                             # WEBJS engine
        or data.get("gid", {}).get("_serialized")     # older WEBJS
        or data.get("gid", {}).get("user", "") + "@g.us"
    )
    if not group_id or group_id == "@g.us":
        raise ValueError(f"Could not parse group ID from response: {data}")
    print(f"  Created '{name}'  ->  {group_id}")
    time.sleep(2)   # avoid WAHA rate-limit between group creations
    return group_id


def archive_chat(client: httpx.Client, session: str, chat_id: str) -> bool:
    """POST /api/{session}/chats/{chatId}/archive  →  True if succeeded."""
    r = client.post(f"/api/{session}/chats/{chat_id}/archive")
    if r.status_code == 501:
        return False  # engine does not support this endpoint
    r.raise_for_status()
    print(f"  Archived {chat_id} from session '{session}'")
    return True

# ---------------------------------------------------------------------------
# Asset generators (stdlib only)
# ---------------------------------------------------------------------------

def make_minimal_png() -> bytes:
    """Build a 1x1 red pixel PNG using only stdlib."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    # IHDR: width=1, height=1, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    # IDAT: filter-byte(0) + R=255, G=0, B=0  →  1x1 red pixel
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xFF\x00\x00"))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


def make_minimal_wav() -> bytes:
    """Build a 1-second silent mono WAV at 8 kHz using only stdlib."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)          # 8-bit
        w.setframerate(8000)       # 8 kHz
        w.writeframes(b"\x80" * 8000)  # silence (128 = midpoint for unsigned 8-bit PCM)
    return buf.getvalue()


def create_assets() -> None:
    ASSETS_DIR.mkdir(exist_ok=True)
    img = ASSETS_DIR / "test_image.png"
    if not img.exists():
        img.write_bytes(make_minimal_png())
        print(f"  Created {img}")
    else:
        print(f"  Skipped {img} (already exists)")

    voice = ASSETS_DIR / "test_voice.wav"
    if not voice.exists():
        voice.write_bytes(make_minimal_wav())
        print(f"  Created {voice}")
    else:
        print(f"  Skipped {voice} (already exists)")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Wet Test Setup ===\n")

    print("Creating test assets:")
    create_assets()
    print()

    with make_client() as client:
        print("Scenario A — archived from BOTH sender and listener:")
        group_a1 = create_group(client, SENDER_SESSION, "WetTest-BothArchived-1")
        group_a2 = create_group(client, SENDER_SESSION, "WetTest-BothArchived-2")

        print("\nScenario B — archived from sender ONLY:")
        group_b1 = create_group(client, SENDER_SESSION, "WetTest-SenderArchived-1")
        group_b2 = create_group(client, SENDER_SESSION, "WetTest-SenderArchived-2")

        print("\nArchiving Scenario A groups from both sessions:")
        archive_supported = True
        for gid in (group_a1, group_a2):
            ok = archive_chat(client, SENDER_SESSION, gid)
            if ok:
                archive_chat(client, ADIAMI_SESSION, gid)
            else:
                archive_supported = False
                break

        if not archive_supported:
            print("\n  NOTE: Archive API not supported by this WAHA engine (GOWS).")
            print("  Please archive the groups MANUALLY from the phone:")
            print(f"\n  Scenario A — archive from BOTH sender AND listener:")
            print(f"    {group_a1}  (WetTest-BothArchived-1)")
            print(f"    {group_a2}  (WetTest-BothArchived-2)")
            print(f"\n  Scenario B — archive from SENDER ONLY:")
            print(f"    {group_b1}  (WetTest-SenderArchived-1)")
            print(f"    {group_b2}  (WetTest-SenderArchived-2)")
        else:
            print("\nArchiving Scenario B groups from sender only:")
            for gid in (group_b1, group_b2):
                archive_chat(client, SENDER_SESSION, gid)

    state = {
        "groups": {
            "both_archived":    [group_a1, group_a2],
            "sender_archived":  [group_b1, group_b2],
        },
        "private_chat":    ADIAMI_JID,
        "sender_session":  SENDER_SESSION,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"\nState saved  ->  {STATE_FILE}")
    print("\nSetup complete. Run run_tests.py to execute the wet tests.")


if __name__ == "__main__":
    main()
