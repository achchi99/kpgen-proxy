"""kpgen VPS proxy — FastAPI ilova.

Vazifasi: kpgen desktop dasturidan kelgan so'rovlarni Anthropic API'ga
yo'naltiradi (API kalit faqat shu serverda, kodda emas — CLAUDE.md §6).
"""

import base64
import binascii
import re
from io import BytesIO

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from app.anthropic_client import ProxyError, ask_claude, ask_claude_vision

app = FastAPI(title="kpgen-proxy")

_NUMBER_RE = re.compile(r"^\d+([.,]\d+)?$")


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Server hech qachon qulamasin — kutilmagan har qanday xato ham
    tushunarli JSON bo'lib qaytadi."""
    return JSONResponse(status_code=500, content={"error": f"Kutilmagan server xatosi: {exc}"})


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1)


class ClassifyResponse(BaseModel):
    category: str


class VisionRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    context: str = ""


class VisionResponse(BaseModel):
    value: str | None
    confidence: str  # "high" | "low"


_CLASSIFY_PROMPT = (
    "Sen ventilyatsiya jihozlari nomlarini tasniflaydigan yordamchisan. "
    "Quyidagi nomga eng mos keladigan qisqa kategoriya nomini rus tilida, "
    "boshqa hech qanday izohsiz, faqat kategoriya nomining o'zini qaytar:\n\n"
    "{text}"
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify(payload: ClassifyRequest):
    try:
        category = ask_claude(_CLASSIFY_PROMPT.format(text=payload.text))
    except ProxyError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    return ClassifyResponse(category=category)


@app.post("/vision", response_model=VisionResponse)
def vision(payload: VisionRequest):
    try:
        image_bytes = base64.b64decode(payload.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return JSONResponse(status_code=422, content={"error": f"image_base64 buzuq: {exc}"})

    try:
        Image.open(BytesIO(image_bytes)).verify()
    except (UnidentifiedImageError, OSError) as exc:
        return JSONResponse(status_code=422, content={"error": f"image_base64 haqiqiy rasm emas: {exc}"})

    try:
        raw_value = ask_claude_vision(payload.image_base64, payload.context)
    except ProxyError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    # Server-tomon QAT'IY validatsiya — modelning o'z ishonchini so'ramaymiz,
    # javob toza raqam bo'lsa "high", aks holda (shu jumladan "null") "low".
    cleaned = raw_value.strip()
    if _NUMBER_RE.match(cleaned):
        return VisionResponse(value=cleaned, confidence="high")

    return VisionResponse(value=None, confidence="low")
