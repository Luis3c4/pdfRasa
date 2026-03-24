# OCR Payment Validation — Documentación de implementación

## Estado de las fases

| Fase | Descripción | Estado |
|---|---|---|
| Phase 1 | Módulo OCR aislado (`ocr_validator.py`) | ✅ Implementada |
| Phase 2 | Acción validate con OCR integrado | ✅ Implementada |
| Phase 3 | Modelo `Order` con campo `status` + `create_order` actualizado | ✅ Implementada |
| Phase 4 | Escalada a agente humano en Chatwoot | ✅ Implementada |
| Phase 5 | Dominio y flujo de compra actualizados con branching | ✅ Implementada |

---

## Flujo completo de validación de pago

```
Usuario envía imagen de captura de pago
            │
            ▼
[validate_payment_screenshot_url]  ← validate_payment_screenshot.py
  Extrae URL de imagen del metadata (Chatwoot / Meta / Twilio)
  Llama a ocr_validator.validate_payment()
            │
            ├── Sin imagen → SlotSet(payment_screenshot_url=None)
            │                  → flujo repide la captura
            │
            ├── OCR → "approved" (4/4 checks)
            │           → SlotSet(payment_validation_status="approved")
            │
            ├── OCR → "needs_review" (1-3/4 checks)
            │           → SlotSet(payment_validation_status="needs_review")
            │
            └── OCR → "rejected" (0/4 checks)
                        → SlotSet(payment_validation_status="rejected")

            │
            ▼
[purchase.yml — branching]
  payment_screenshot_url = null    → wait_for_screenshot (repide imagen)
  payment_validation_status = "approved"     → create_order → release_download
  payment_validation_status = "needs_review" → create_order_pending → escalate_human
  else (rejected)                            → ocr_rejected → wait_for_screenshot

            │ (ruta approved)
            ▼
[action_create_order]  ← action_create_order.py
  Lee slots: selected_book_id, book_title, payment_screenshot_url, payment_validation_status
  Llama catalog.create_order(status="approved")
  Guarda orden en orders.json con status correcto
            │
            ▼
[action_release_download]  ← action_release_download.py (sin modificar)
  Lee book de catálogo por selected_book_id
  Envía mensaje con link de descarga al cliente
  Resetea slots de sesión

            │ (ruta needs_review)
            ▼
[action_create_order]
  Crea orden con status="needs_review"
            │
            ▼
[action_escalate_to_human]  ← action_escalate_to_human.py
  Extrae conversation_id de tracker.sender_id ("chatwoot_{id}")
  PATCH /api/v1/accounts/{id}/conversations/{conv_id} → {"status": "pending"}
  Conversación aparece en cola de agentes en Chatwoot
  Envía mensaje al cliente: "Un agente revisará y te enviará el enlace"

            │ (ruta rejected)
            ▼
[utter_payment_ocr_rejected]
  Pide al cliente reenviar captura completa
  Vuelve a wait_for_screenshot
```

---

## Archivos nuevos

### `actions/ocr_validator.py`
Módulo OCR completamente aislado de Rasa. No importa nada de `rasa_sdk`.

**Funciones:**
- `_get_reader()` — inicializa EasyOCR Reader una sola vez (singleton, `gpu=False`, compartiendo PyTorch existente)
- `_download_image(url)` — descarga imagen con `httpx`, timeout 15s
- `_enhance_for_ocr(img)` — upscale 2x + contraste 2.0 con Pillow (compensa compresión JPEG de WhatsApp)
- `extract_text(image_url)` — orquesta descarga + enhancement + OCR, retorna texto crudo
- `_parse_amount(text)` — regex `S/\s*\d+[.,]\d{2}`, tolerante a confusión `/` → `I|`
- `_parse_date(text)` — regex para `DD/MM/YYYY` y `DD mmm YYYY`
- `_parse_reference(text)` — busca código de operación (6-12 dígitos) tras keywords de Yape
- `parse_yape_data(text)` — retorna `{monto, fecha, referencia}`
- `validate_payment(image_url, expected_amount, yape_number)` — función principal, retorna:
  ```python
  {
    "status": "approved" | "needs_review" | "rejected",
    "checks": {
      "monto_correcto": bool,   # monto OCR == precio del libro
      "numero_destino": bool,   # 912201963 aparece en el texto
      "pago_exitoso": bool,     # keywords "exitoso", "enviaste", etc.
      "fecha_hoy": bool,        # fecha del día en la captura
    },
    "data": {"monto": float, "fecha": str, "referencia": str},
    "raw_text": str,
  }
  ```
  - 4/4 checks → `"approved"` (entrega automática)
  - 1-3/4 checks → `"needs_review"` (escala a humano)
  - 0/4 checks → `"rejected"` (pide reenviar)

---

### `actions/action_escalate_to_human.py`
Acción Rasa que mueve la conversación a la cola de agentes en Chatwoot.

**Variables de entorno requeridas:**
```bash
CHATWOOT_URL=http://localhost:3000
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_ACCESS_TOKEN=<token del bot/agente>
```

**Lógica:**
1. Extrae `conversation_id` desde `tracker.sender_id` (formato: `chatwoot_{id}`)
2. Llama `PATCH /api/v1/accounts/{account_id}/conversations/{conversation_id}` con `{"status": "pending"}`
3. Si el API call falla, loguea el error pero igual envía el mensaje al cliente (no rompe el flujo)
4. Envía `utter_payment_needs_review` al cliente

---

## Archivos modificados

### `actions/validate_payment_screenshot.py`
Antes solo extraía la URL de imagen. Ahora:
- Refactoriza la extracción de URL al método `_extract_image_url(metadata)`
- Agrega `_get_expected_amount(tracker)` que lee `book_price` slot (o busca en catálogo por `selected_book_id`)
- Llama `ocr_validator.validate_payment()` con la URL, monto esperado y número Yape
- Retorna dos slots: `payment_screenshot_url` + `payment_validation_status`
- Si OCR lanza excepción → `needs_review` por defecto (nunca rechaza por error técnico)

### `actions/catalog.py`
- Modelo `Order`: nuevo campo `status: str = "approved"` (retrocompatible con órdenes existentes)
- Función `create_order()`: acepta nuevo parámetro `status: str = "approved"` y lo persiste

### `actions/action_create_order.py`
- Lee slot `payment_validation_status` (default `"needs_review"` si es None)
- Pasa `status=validation_status` a `catalog.create_order()`
- Las órdenes en `orders.json` ahora registran si fueron aprobadas automáticamente o están pendientes de revisión

### `actions/action_reset_purchase_slots.py`
- Agrega `SlotSet("payment_validation_status", None)` al reset (limpia el slot para próxima compra)

### `domain/purchase.yml`
- Nuevo slot `payment_validation_status` (type: text, mapping: controlled)
- Nueva action `action_escalate_to_human`
- Nueva response `utter_payment_ocr_rejected` — pide reenviar captura completa
- Nueva response `utter_payment_needs_review` — notifica que un agente revisará

### `data/flows/purchase.yml`
Reemplaza el step `validate_screenshot` con branching de 3 rutas:

```yaml
- id: validate_screenshot
  action: validate_payment_screenshot_url
  next:
    - if: "slots.payment_screenshot_url is null"        → wait_for_screenshot
    - if: "slots.payment_validation_status = 'approved'"  → create_order
    - if: "slots.payment_validation_status = 'needs_review'" → create_order_pending
    - else:                                               → ocr_rejected

- id: ocr_rejected          → utter_payment_ocr_rejected → wait_for_screenshot
- id: create_order          → action_create_order → release_download → END
- id: release_download      → action_release_download → END
- id: create_order_pending  → action_create_order → escalate_human → END
- id: escalate_human        → action_escalate_to_human → END
```

---

## Dependencias nuevas

```bash
pip install easyocr      # ~50MB adicionales (usa PyTorch ya instalado)
pip install httpx        # probablemente ya instalado
pip install pillow       # probablemente ya instalado
```

**No se requiere:** OpenCV, GPU adicional, segundo modelo vLLM, cuenta de nube externa.

---

## Variables de entorno a agregar

```bash
# En .env o en el entorno antes de iniciar las actions
export CHATWOOT_URL="http://localhost:3000"
export CHATWOOT_ACCOUNT_ID="1"
export CHATWOOT_ACCESS_TOKEN="<token>"
```

---

## Cómo probar manualmente el módulo OCR

```python
# Desde el directorio pdfRasa/
from actions.ocr_validator import validate_payment

result = validate_payment(
    image_url="https://i.ibb.co/CpK3mrS0/15c01ddd-bfa3-41de-ae3c-7623875d90ff.jpg",
    expected_amount=15,
    yape_number="912201963",
)
print(result["status"])   # "approved" | "needs_review" | "rejected"
print(result["checks"])   # detalle de cada verificación
print(result["data"])     # monto, fecha, referencia extraídos
```
