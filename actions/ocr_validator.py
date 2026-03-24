"""OCR-based payment screenshot validator for Yape (Peru).

Uses EasyOCR on CPU — no extra VRAM needed (shares PyTorch already installed).
The EasyOCR Reader is instantiated once at module level to avoid expensive
re-loading (~10s) on every request.

Typical usage:
    from actions.ocr_validator import validate_payment

    result = validate_payment(
        image_url="https://...",
        expected_amount=25,
        yape_number="912201963",
    )
    # result["status"] -> "approved" | "needs_review" | "rejected"
"""

import asyncio
import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import httpx
import numpy as np
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton EasyOCR reader — instantiated once to avoid 10s reload per request
# ---------------------------------------------------------------------------
_reader = None

# Thread pool for running CPU-bound OCR without blocking the async event loop.
# max_workers=2 allows 2 concurrent OCR jobs; torch/numpy release the GIL
# so both threads genuinely run in parallel on CPU.
_executor = ThreadPoolExecutor(max_workers=2)


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # lazy import so the module can be imported without easyocr installed
        logger.info("Initializing EasyOCR reader (first use)…")
        _reader = easyocr.Reader(["es", "en"], gpu=False)
        logger.info("EasyOCR reader ready.")
    return _reader


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _download_image(image_url: str) -> Image.Image:
    response = httpx.get(image_url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def _enhance_for_ocr(img: Image.Image) -> Image.Image:
    """Upscale and boost contrast to counteract WhatsApp JPEG compression."""
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(image_url: str) -> str:
    """Download image, pre-process, run EasyOCR and return joined text."""
    try:
        img = _download_image(image_url)
        img = _enhance_for_ocr(img)
        img_array = np.array(img)  # EasyOCR requires numpy array, not PIL Image
        reader = _get_reader()
        lines = reader.readtext(img_array, detail=0, paragraph=False)
        return "\n".join(lines)
    except Exception as exc:
        logger.error("OCR extraction failed for %s: %s", image_url, exc)
        return ""


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def _parse_amount(text: str) -> Optional[float]:
    """Extract the payment amount from Yape screenshot text.

    Matches patterns like: "S/ 25.00", "S/25,00", "S/ 25"
    """
    match = re.search(r"[Ss][/I\|]\s*\.?\s*(\d{1,5})[,.](\d{2})", text)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    # Fallback: integer amount without decimals
    match = re.search(r"[Ss][/I\|]\s*(\d{1,5})\b", text)
    if match:
        return float(match.group(1))
    return None


def _parse_date(text: str) -> Optional[str]:
    """Extract date string from text. Returns DD/MM/YYYY or similar."""
    match = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", text)
    if match:
        return match.group(0)
    # "23 mar 2026" / "23 Mar. 2026"
    match = re.search(
        r"\b(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z.:]*\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(0)
    return None


def _parse_reference(text: str) -> Optional[str]:
    """Extract the Yape operation code / reference number (6-12 digits)."""
    match = re.search(
        r"(?:operaci[oó]n|referencia|c[oó]digo|n[uú]mero)[^\d]{0,10}(\d{6,12})",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return None


def parse_yape_data(text: str) -> dict:
    return {
        "monto": _parse_amount(text),
        "fecha": _parse_date(text),
        "referencia": _parse_reference(text),
    }


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_payment(
    image_url: str,
    expected_amount: int,
    yape_number: str = "923252274",
) -> dict:
    """Validate a Yape payment screenshot.

    Returns:
        {
            "status": "approved" | "needs_review" | "rejected",
            "checks": {
                "monto_correcto": bool,
                "numero_destino": bool,
                "pago_exitoso": bool,
                "fecha_hoy": bool,
            },
            "data": {"monto": float|None, "fecha": str|None, "referencia": str|None},
            "raw_text": str,
        }
    """
    raw_text = extract_text(image_url)
    lower_text = raw_text.lower()
    data = parse_yape_data(raw_text)

    today = datetime.now().strftime("%d/%m/%Y")
    today_day = datetime.now().strftime("%d")
    today_year = str(datetime.now().year)

    # fecha_hoy: acepta formato numérico (23/03/2026) o textual (23 mar: 2026)
    fecha_hoy = (today in raw_text) or (
        data["fecha"] is not None
        and today_day in data["fecha"]
        and today_year in data["fecha"]
    )

    checks = {
        "monto_correcto": data["monto"] is not None and abs(data["monto"] - float(expected_amount)) < 0.05,
        # Yape always masks the destination number, showing only the last 3 digits
        # (e.g. "*** *** 963"). Checking those 3 digits is sufficient.
        "numero_destino": bool(re.search(r'\b' + re.escape(yape_number[-3:]) + r'\b', raw_text)),
        "pago_exitoso": any(
            keyword in lower_text
            for keyword in ["exitoso", "enviaste", "transferencia realizada", "pago realizado", "completado", "yapeaste"]
        ),
        "fecha_hoy": fecha_hoy,
    }

    passed = sum(checks.values())

    if passed == 4:
        status = "approved"
    elif passed >= 1:
        status = "needs_review"
    else:
        status = "rejected"

    logger.info(
        "OCR validation for %s → status=%s checks=%s data=%s",
        image_url,
        status,
        checks,
        data,
    )

    return {
        "status": status,
        "checks": checks,
        "data": data,
        "raw_text": raw_text,
    }


async def validate_payment_async(
    image_url: str,
    expected_amount: int,
    yape_number: str = "923252274",
) -> dict:
    """Non-blocking wrapper around validate_payment for use in async actions.

    Runs the CPU-bound OCR in a thread pool so the Sanic event loop
    is not blocked and concurrent users are served in parallel.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        validate_payment,
        image_url,
        expected_amount,
        yape_number,
    )
