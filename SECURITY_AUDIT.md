# Security Audit Report — Pre-GitHub Release

**Date:** 2026-06-22  
**Scope:** All source files in the `notify_delete/` project

---

## Findings & Fixes

### HIGH — Real personal phone number hardcoded in source

| File | Line | Finding |
|---|---|---|
| `wet_tests/setup_groups.py` | 37 | `ADIAMI_JID = "972549747174@c.us"` — real Israeli mobile number |

**Fix:** Replaced with `os.environ.get("WET_TEST_LISTENER_JID", "972500000000@c.us")` so the real number is never committed; users supply it via env.

---

### HIGH — Real WhatsApp group ID in committed source files

| File | Location | Finding |
|---|---|---|
| `.env.example` | `NOTIFY_GROUP_ID=` | `120363407713984498@g.us` — real group ID used as "example" |
| `useful_files/node_red_main_flow.js` | `notify_group` env var + inject node | Same real group ID appeared twice |
| `README.md` (old) | curl example payloads | Same real group ID in copy-paste examples |

**Fix:** All replaced with `YOUR_GROUP_JID@g.us` placeholder. README examples updated to a clearly synthetic ID.

---

### MEDIUM — Private LAN IP address in committed source

| File | Location | Finding |
|---|---|---|
| `useful_files/node_red_main_flow.js` | `Set send file vars` function | `http://192.168.10.246:8123/local/media/` — private Home Assistant IP |

**Fix:** Replaced with `YOUR_HOME_ASSISTANT_IP`.

---

### MEDIUM — Personal WAHA session names hardcoded as defaults

| File | Location | Finding |
|---|---|---|
| `app/config.py` | `waha_listen_session` default | `"adiami"` — owner's personal session name |
| `wet_tests/setup_groups.py` | `YARDEN_SESSION` | `"yarden"` — hardcoded personal name |
| `wet_tests/setup_groups.py` | `ADIAMI_SESSION` fallback | `"adiami"` as fallback |
| `.env.example` | `WAHA_LISTEN_SESSION=` | `adiami` as suggested value |
| `wet_tests/README.md` | Table + usage text | Both names used throughout |

**Fix:** 
- `app/config.py` default changed to `"listener"` (generic)
- `wet_tests/setup_groups.py` refactored: `YARDEN_SESSION` → `SENDER_SESSION` read from `WET_TEST_SENDER_SESSION` env var; `ADIAMI_SESSION` fallback changed to `"listener"`
- `.env.example` updated to `listener`
- `wet_tests/README.md` fully rewritten with generic role names

---

### MEDIUM — Live SQLite database and captured WhatsApp media not gitignored

| Path | Finding |
|---|---|
| `data/bot.db` | Contains captured WhatsApp message content (PII) |
| `data/data/bot.db` | Duplicate database |
| `data/data/media/*.jpeg` | Captured media from real conversations |

**Fix:** Created root `.gitignore` with `data/` excluded. These files will never be committed.

---

### LOW — Real phone numbers in gitignored test data files

| File | Finding |
|---|---|
| `wet_tests/state.json` | `"private_chat": "972549747174@c.us"` and 4 real group IDs — gitignored by `wet_tests/.gitignore` |
| `wet_tests/messages.json` | Phone `972523752473` embedded in WAHA message API IDs — gitignored |

**Fix:** Files were already gitignored (would not have been committed). Sanitized in-place anyway: `state.json` replaced with placeholder structure; `messages.json` cleared to `[]`.

---

### LOW — Claude Code local settings with embedded IP not gitignored

| File | Finding |
|---|---|
| `.claude/settings.local.json` | Permission note contains `192.168.10.246` (local machine IP) |

**Fix:** Added `.claude/settings.local.json` to root `.gitignore`.

---

### LOW — Virtual environment not gitignored

| Path | Finding |
|---|---|
| `.venv/` | Python virtual environment; large, not needed in source control |

**Fix:** Added `.venv/` to root `.gitignore`.

---

## Files Created / Modified

| File | Action |
|---|---|
| `.gitignore` | **Created** — excludes `.env`, `data/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.claude/settings.local.json` |
| `app/config.py` | Fixed default session name `"adiami"` → `"listener"` |
| `.env.example` | Fixed real group ID → placeholder; fixed session name; added wet-test vars |
| `useful_files/node_red_main_flow.js` | Replaced private IP and real group ID |
| `wet_tests/setup_groups.py` | Replaced hardcoded phone number + personal session names with env-var-driven generics |
| `wet_tests/run_tests.py` | Updated state key reference (`yarden_archived` → `sender_archived`) |
| `wet_tests/state.json` | Sanitized real data (file is gitignored) |
| `wet_tests/messages.json` | Cleared real message IDs (file is gitignored) |
| `wet_tests/README.md` | Fully rewritten with generic session names |
| `README.md` | Full rewrite: WAHA paid disclaimer, complete setup guide, removed all personal identifiers |

---

## No Issues Found In

- `app/main.py`, `app/database.py`, `app/handlers/`, `app/services/`, `app/waha/client.py` — no hardcoded secrets
- `app/admin/auth.py`, `app/admin/router.py` — credentials read from env only
- `tests/` — no real data used
- `docker-compose.yml` — no embedded credentials
- `Dockerfile` — no embedded credentials
- `useful_files/waha_openapi.json` — vendor API spec, no personal data
