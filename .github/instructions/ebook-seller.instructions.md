---
description: "Use when working on the pdfRasa ebook sales chatbot: adding books, editing flows, creating actions, handling Yape payment, WhatsApp image detection, or releasing download links. Covers the full Rasa CALM architecture for this project."
applyTo: "pdfRasa/**"
---

# pdfRasa — Ebook Sales Chatbot (Rasa CALM)

## Project Purpose
Chatbot for selling PDF ebooks via WhatsApp. Customers browse a catalog, get book details, pay via **Yape** (phone number **912201963**), send a payment screenshot, and automatically receive a download link.

---

## Architecture Overview

| Layer | Technology | Notes |
|-------|-----------|-------|
| Framework | Rasa 3.5+ (CALM / Flow-based) | `recipe: default.v1` |
| LLM | Qwen 2.5-7B-Instruct (port 8000) | Slot extraction only |
| Embeddings | BAAI/bge-m3 (port 8001) | Flow retrieval |
| Channel | WhatsApp (Twilio or Meta Business API) | See `credentials.yml` |
| DB | JSON files per session | Copied to `/tmp/ebook_bot/{sender_id}/` |
| Payment | Yape — number 912201963 | No API verification, user sends screenshot |

---

## Key Files

| File | Purpose |
|------|---------|
| `db/catalog.json` | Catalog of ebooks — edit here to add/change books |
| `db/orders.json` | Order registry (starts empty, grows at runtime in temp) |
| `actions/catalog.py` | DB layer: `Book`, `Order` models + CRUD functions |
| `actions/action_show_catalog.py` | Formats and sends full catalog to user |
| `actions/action_get_book_details.py` | Shows description, pages, price; sets `book_title` + `book_price` slots |
| `actions/validate_payment_screenshot.py` | **Custom slot validator** — detects WhatsApp image from message metadata |
| `actions/action_create_order.py` | Creates order record, sets `order_id` slot |
| `actions/action_release_download.py` | Sends download link from `book.download_link` |
| `data/flows/browse_catalog.yml` | Flow: show full catalog |
| `data/flows/book_details.yml` | Flow: show one book's details |
| `data/flows/purchase.yml` | Flow: full purchase journey |
| `domain/catalog.yml` | Slots, responses, actions for catalog |
| `domain/purchase.yml` | Slots, responses, actions for purchase |
| `domain/shared.yml` | `return_value` slot (flow branching) |
| `credentials.yml` | WhatsApp Twilio/Meta credentials (commented out) |

---

## Catalog Management

To add or modify books, edit `db/catalog.json` only. Each book must have:

```json
{
  "id": "book_XXX",           // unique, snake_case
  "title": "Book Title",
  "description": "...",
  "pages": 150,
  "price": 30,                // integer, in soles (no decimals)
  "currency": "S/.",
  "preview": "Chapter summary or highlights...",
  "download_link": "https://drive.google.com/file/d/REAL_ID/view?usp=sharing"
}
```

**IMPORTANT**: Replace `REPLACE_WITH_REAL_ID_XXX` in each `download_link` with the actual Google Drive (or other) shareable link before going live.

---

## Flow Design Conventions

- **Slot branching**: use `SlotSet("return_value", "success"|"error"|"not_found")` from actions, then branch in flow YAML with `if: "slots.return_value = 'success'"`.
- **Collect steps**: use `description:` for LLM-based extraction, `ask_before_filling: true` for explicit confirmation steps.
- **All flows** must declare a `description:` for the LLM router to match user intent.
- **Never hardcode prices or book titles** in flow YAML — always read from catalog and use slots.

---

## Purchase Flow (purchase.yml)

```
buyer_name → selected_book_id → action_get_book_details
  → purchase_confirmation (buttons) → utter_payment_instructions
  → payment_screenshot_url (image validator) → action_create_order
  → action_release_download
```

The `utter_payment_instructions` response uses `{book_price}` and `{book_title}` slot variables. These must be set by `action_get_book_details` before this utterance fires.

---

## WhatsApp Image Detection — validate_payment_screenshot_url

The `ValidatePaymentScreenshotUrl` action (in `validate_payment_screenshot.py`) is the **only** way the `payment_screenshot_url` slot is filled. It reads from `tracker.latest_message["metadata"]`:

| Connector | Metadata key |
|-----------|-------------|
| Twilio WhatsApp | `MediaUrl0` |
| Meta Business API | `image.link` or `image.id` |
| Generic fallback | `image_url` |

If no image is found, it sends an error message and returns `SlotSet("payment_screenshot_url", None)` — the flow will re-ask automatically.

**Do NOT use `from_llm` mapping for this slot** — it must stay `type: custom, action: validate_payment_screenshot_url`.

---

## Action Patterns

```python
# Standard return pattern for flow branching
return [SlotSet("return_value", "success")]

# Sending formatted messages
dispatcher.utter_message(text="*Bold* text, emoji 📖")

# Sending utterance with slot substitution
dispatcher.utter_message(response="utter_order_created", order_id=order.order_id)

# DB access always requires session isolation via sender_id
books = get_all_books(tracker.sender_id)
book  = get_book_by_id(tracker.sender_id, book_id)
order = create_order(tracker.sender_id, book_id, book_title, buyer_name, screenshot_url)
```

---

## Domain Conventions

- All slots set by actions use `type: controlled` (never `from_llm`).
- Slots the LLM fills from user input use `type: from_llm` or `type: text` with `from_llm` mapping.
- Use `type: bool` with buttons for confirmation slots.
- `return_value` slot lives in `domain/shared.yml` — never move it.
- One domain file per flow (`catalog.yml`, `purchase.yml`). Never merge them.

---

## Adding a New Book (Step-by-Step)

1. Add entry to `db/catalog.json` with a unique `id` like `book_004`.
2. Replace `download_link` with the real shareable URL.
3. No other files need to change — the catalog actions read dynamically.
4. Run `rasa train` and test with `rasa inspect`.

---

## Running Locally (4 terminals)

```bash
# Terminal 1 — LLM (Qwen 2.5-7B)
vllm serve Qwen/Qwen2.5-7B-Instruct --port 8000

# Terminal 2 — Embeddings (BGE-M3)
vllm serve BAAI/bge-m3 --port 8001

# Terminal 3 — Rasa bot
cd pdfRasa && rasa inspect

# Terminal 4 — Actions server
cd pdfRasa && rasa run actions
```

See `COMMANDS.md` for full GPU/VRAM requirements and flags.

---

## WhatsApp Deployment Checklist

1. Sign up for Twilio (or Meta Business API).
2. Uncomment and fill in credentials in `credentials.yml`.
3. Set webhook URL in Twilio/Meta console to: `https://your-domain.com/webhooks/twilio/webhook`
4. Replace all `download_link` placeholders in `db/catalog.json`.
5. Run `rasa train`.
6. Start all 4 services.
7. Test end-to-end: browse → buy → pay via Yape → send screenshot → receive link.

---

## Security Notes

- Download links are sent directly in chat — use time-limited links (Google Drive "anyone with link" + expiry) for production.
- Yape payment is verified by trust (screenshot), not by API — consider adding manual verification for high-value books.
- `orders.json` is stored per-session in `/tmp` — not persistent across restarts. For production, migrate to SQLite or PostgreSQL.
