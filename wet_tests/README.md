# Wet Tests

Live (real API) tests that require two active WAHA sessions: a **sender** session (sends and deletes messages) and a **listener** session (the bot's monitored session).

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `WAHA_BASE_URL` | `http://localhost:3000` | WAHA server URL |
| `WAHA_API_KEY` | _(required)_ | WAHA API key |
| `WAHA_LISTEN_SESSION` | `listener` | Session the bot monitors |
| `WET_TEST_SENDER_SESSION` | `sender` | Second session used to send/delete test messages |
| `WET_TEST_LISTENER_JID` | _(required)_ | Phone JID of the listener account, e.g. `972501234567@c.us` |

## Test scenarios

| Group name | Created by | Members | Archived from |
|---|---|---|---|
| WetTest-BothArchived-1 | sender | sender + listener | sender + listener |
| WetTest-BothArchived-2 | sender | sender + listener | sender + listener |
| WetTest-SenderArchived-1 | sender | sender + listener | sender only |
| WetTest-SenderArchived-2 | sender | sender + listener | sender only |
| Private chat | — | sender + listener | — |

## Message IDs

Each sent message carries a tag so it is easy to spot on the phone:

| Type | IDs |
|---|---|
| Text | `WET-TEXT-01` … `WET-TEXT-05` |
| Image | `WET-IMG-01` … `WET-IMG-05` |
| Voice | `WET-VOICE-01` … `WET-VOICE-05` (ID visible in logs only) |

Destinations 01-04 are the four groups (in order above); 05 is the private chat.

## Usage

```bash
# 1. Set up groups (run once)
python wet_tests/setup_groups.py

# 2. Send all messages, then delete them
python wet_tests/run_tests.py
```

Both scripts read `WAHA_BASE_URL`, `WAHA_API_KEY`, `WAHA_LISTEN_SESSION`, `WET_TEST_SENDER_SESSION`,
and `WET_TEST_LISTENER_JID` from the project `.env` file (one directory up from `wet_tests/`).

## Generated files (gitignored)

| File | Contents |
|---|---|
| `state.json` | Group IDs written by `setup_groups.py` |
| `messages.json` | API message IDs written by `run_tests.py` |
| `assets/test_image.png` | Minimal 1×1 PNG created by `setup_groups.py` |
| `assets/test_voice.wav` | Minimal 1-second silent WAV created by `setup_groups.py` |
