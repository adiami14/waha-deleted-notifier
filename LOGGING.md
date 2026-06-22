# Logging Flow & Structure

All logs are emitted as structured JSON via **structlog** at the log level configured by `LOG_LEVEL` (default: `INFO`).
Each log line is a JSON object with at minimum: `event`, `level`, `timestamp`.

---

## Log Flow by Event Type

### `message.any` — Capturing incoming messages

| Step | Level | Event key | Key fields | Purpose |
|------|-------|-----------|------------|---------|
| Webhook received | INFO | `webhook received` | `event`, `event_id`, `payload` (full raw JSON) | **Full raw webhook payload** — primary source for debugging trigger issues |
| Missing message ID | WARNING | `message.any: missing message id, skipping` | — | Malformed event from WAHA |
| Caption from body | INFO | `caption extracted from body (no explicit caption field)` | `message_id`, `chat_id`, `caption_preview` | Parsing: caption came from body field, not explicit caption field |
| Media but no URL/mimetype | WARNING | `media present but url or mimetype missing — file will NOT be cached` | `message_id`, `chat_id`, `has_url`, `has_mimetype` | **Parsing problem**: file will be missing at delete time |
| Media download failed | ERROR | `media download failed` | `message_id`, `error` | File won't be available for notification |
| Media saved | INFO | `media saved` | `message_id`, `path`, `size` | Confirmation of successful file cache |
| Message captured | INFO | `message captured` | `message_id`, `chat_id`, `has_media`, `has_file`, `caption`, `body_len`, `mime_type` | Summary of what was stored |

---

### `message.revoked` — Processing a deletion

| Step | Level | Event key | Key fields | Purpose |
|------|-------|-----------|------------|---------|
| Webhook received | INFO | `webhook received` | `event`, `event_id`, `payload` (full raw JSON) | **Full raw webhook payload** for the revoke event |
| Missing id/chat_id | WARNING | `revoke event missing id/chat_id` | `event_keys` | Trigger problem: can't identify what was deleted |
| Status/broadcast skipped | INFO | `revoke skipped – status/broadcast` | `chat_id` | Expected skip — not a real chat |
| Revoke received | INFO | `revoke received` | `message_id`, `chat_id`, `is_group`, `sender`, `display_name` | Core trigger info |
| Before payload (full) | INFO | `revoke before payload (full)` | `payload` (the `before` snapshot of the deleted message) | **Full raw before-snapshot** for debugging ID extraction and field parsing |
| Archived from WAHA live | INFO | `archived state learned from WAHA overview` | `chat_id` | State update |
| Chat overview failed | WARNING | `get_chat_overview failed` | `chat_id`, `error` | Non-fatal, archived check degraded |
| Archived suppressed | INFO | `archived notification suppressed by setting` | `chat_id` | Expected skip |
| NOTIFY_GROUP_ID missing | ERROR | `NOTIFY_GROUP_ID not configured` | — | Fatal config error |
| Contact name resolved | INFO | `contact name resolved` | `jid`, `name` | Parsing: sender name from address book |
| LID → phone | INFO | `lid resolved to phone jid` | `lid`, `phone` | Parsing: WEBJS LID resolved to phone JID |
| Contact name extraction failed | WARNING | `contact_name_extraction_failed` | `jid`, `contact_keys`, `contact_preview` | Engine returned contact but no name field found |
| get_contact error | WARNING | `get_contact error` | `jid`, `error` | WAHA API call failed |
| LID resolve error | WARNING | `lid_to_phone error` | `lid`, `error` | LID → phone resolution failed |
| Group name: no name in response | WARNING | `get_group returned no usable name field` | `group_jid`, `keys` | Parsing: group found but name fields missing |
| get_group failed | WARNING | `get_group failed` | `group_jid`, `error` | WAHA API call failed |
| Names resolved | INFO | `names resolved` | `sender_name`, `group_name`, `is_group` | Final resolved names that will appear in notification |
| Fallback ID found | INFO | `stored message found via fallback id` | `fallback_id` | ID reconstruction succeeded on second try |
| **Stored message NOT found** | WARNING | `stored message NOT found — notification will have no content` | `primary_id`, `fallback_ids`, `chat_id`, `sender_jid` | **Parsing problem** + **Goal C**: message was never captured, content is lost |
| Stored message found | INFO | `stored message lookup` | `message_id`, `found`, `has_media`, `has_file`, `file_path`, `caption`, `mime_type`, `body_preview` (up to 200 chars), `is_archived` | **Goal C**: full content of what was deleted |
| Sending image notification | INFO | `sending image notification` | `notify_target`, `caption`, `file_path` | Confirm image path before sending |
| Sending file notification | INFO | `sending file notification` | `notify_target`, `filename`, `mime_type`, `file_path` | Confirm file path before sending |
| Sending text notification | INFO | `sending text notification` | `notify_target`, `body_preview` | Confirm text content before sending |
| **Media file missing from disk** | WARNING | `media file missing from disk — sending text-only fallback` | `has_media`, `file_path`, `file_exists`, `mime_type`, `caption`, `message_id` | **Parsing problem**: media was stored in DB but file gone (download failed earlier or cleanup ran) |
| Sending unavailable fallback | INFO | `sending unavailable fallback notification` | `notify_target` | Fallback path: no stored message at all |
| Notification text sent | INFO | `notification text sent` | `chat_id` | Delivery confirmation |
| Notification image sent | INFO | `notification image sent` | `chat_id` | Delivery confirmation |
| Notification file sent | INFO | `notification file sent` | `chat_id` | Delivery confirmation |
| send_text failed | ERROR | `send_text failed` | `error` | WAHA delivery error |
| send_image failed | ERROR | `send_image failed` | `error` | WAHA delivery error |
| send_file failed | ERROR | `send_file failed` | `error` | WAHA delivery error |

---

### `chat.archive` — Archived state change

| Step | Level | Event key | Key fields | Purpose |
|------|-------|-----------|------------|---------|
| Webhook received | INFO | `webhook received` | `event`, `event_id`, `payload` | Full raw event |
| State updated | INFO | `chat archive updated` | `chat_id`, `archived` | Confirms DB update |

---

## Diagnosing Problems

### A. Trigger problems — "I expected a notification but got nothing"

1. Search logs for `"webhook received"` with `event=message.revoked` — confirms WAHA delivered the event
2. Check for `"revoke event missing id/chat_id"` — payload was malformed
3. Check for `"revoke skipped – status/broadcast"` — expected skip for status updates
4. Check for `"NOTIFY_GROUP_ID not configured"` — env var missing
5. Check for `"handler error"` in main.py — unexpected exception swallowed the event

### B. Parsing problems — "Notification sent but content/image was missing"

**Image/file missing:**
- At capture time: `"media present but url or mimetype missing — file will NOT be cached"` — WAHA didn't provide download URL yet
- At capture time: `"media download failed"` — download error
- At notify time: `"media file missing from disk — sending text-only fallback"` — file was expected but gone (cleanup or disk issue)

**Wrong sender name:**
- `"contact_name_extraction_failed"` — contact found but fields don't match any known name field
- `"contact name resolved"` — shows what name was chosen and from which JID

**Wrong group name:**
- `"get_group returned no usable name field"` — group found but name fields missing
- `"names resolved"` — shows final `group_name`

**Caption extracted from wrong field:**
- `"caption extracted from body (no explicit caption field)"` — caption came from `body`, not `caption`

### C. Recovering deleted content

When you need to see what the deleted message contained:

1. Find `"stored message lookup"` for the `message_id` — contains:
   - `body_preview` (up to 200 chars of the text body)
   - `caption` (media caption)
   - `has_media`, `mime_type`, `file_path`
2. If `"stored message NOT found"` — the message was never captured by the bot (arrived before the bot started, or `message.any` was not enabled in WAHA)
3. The `"revoke before payload (full)"` log contains the raw `before` snapshot from WAHA — this may include additional content fields depending on the engine

---

## Log Levels

| Level | When used |
|-------|-----------|
| `ERROR` | Fatal: notification cannot be sent (WAHA send failed, config missing) |
| `WARNING` | Degraded operation: content missing, name resolution failed, file not cached |
| `INFO` | Normal operation milestones: webhook received, message captured, names resolved, notification sent |
| `DEBUG` | Verbose internal state (only visible when `LOG_LEVEL=DEBUG`) |


