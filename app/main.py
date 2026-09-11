"""kpgen VPS proxy — FastAPI ilova.

Vazifasi: kpgen desktop dasturidan kelgan so'rovlarni Anthropic API'ga
yo'naltiradi (API kalit faqat shu serverda, kodda emas — CLAUDE.md §6).
"""

import base64
import binascii
import json
import logging
import re
from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

from app.anthropic_client import ProxyError, ask_claude, ask_claude_dwg_spec, ask_claude_vision

# Faza-68-topshiriq (mijoz, 2026-09-11, "biz ko'r holda ishlayapmiz"):
# `logging.basicConfig()` ILGARI HECH QAYERDA chaqirilmagan edi — bu
# modul VA `anthropic_client.py`dagi barcha `_log.info(...)` chaqiruvlari
# (masalan /dwg_spec so'rovlari, tekshiruv natijalari) Python logging
# modulining standart xatti-harakati bo'yicha JIMGINA yo'qolardi (handler
# yo'q). journalctl'da xizmatning ISHGA TUSHISH xabari HAM ko'rinmasdi —
# kpgen (asosiy repo) tomonida `web/worker.py` diagnostikasida topilgan
# aynan shu muammo, bu yerda ham bir xil sabab bilan tuzatiladi. Daraja
# INFO (diagnostika uchun yetarli, shovqin emas).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

_log = logging.getLogger("kpgen_proxy")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _log.info("kpgen-proxy ishga tushdi")
    yield


app = FastAPI(title="kpgen-proxy", lifespan=_lifespan)

_NUMBER_RE = re.compile(r"^\d+([.,]\d+)?$")

# Faza-45-topshiriq §B (haqiqiy xato #3, Мимар sinovi, 2026-09-08):
# promptda "faqat JSON, boshqa hech qanday matn yozma" deb qat'iy
# talab qilingan bo'lsa ham, model ba'zan JSON'ni tabiiy-til izohi va/
# yoki markdown ```json...``` kod bloki bilan o'rab qaytaradi — bunda
# `json.loads()` xom matnni to'g'ridan-to'g'ri qabul qila olmaydi.
# Bu — model "yolg'on" gapiryapti degani EMAS (Мимар sinovida model
# ICHKI JSON'i 100% to'g'ri edi, faqat qatlamlash muammosi bor edi) —
# shuning uchun buni "xato" deb rad etishdan ko'ra, JSON qismini xavfsiz
# ajratib olish to'g'riroq. Bu ajratib olingandan KEYIN ham xuddi
# avvalgidek qat'iy schema-tekshiruv (`DwgSpecResponse.model_validate`)
# ishlaydi — bu funksiya faqat qaysi qism JSON ekanini topadi, mazmunini
# tekshirmaydi.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _extract_json_object(raw: str) -> str:
    """Model javobidan JSON obyektini ajratib oladi — kod blokidagi,
    yoki matn ichidagi birinchi `{`dan oxirgi `}`gacha bo'lgan qismni.
    Hech narsa topilmasa xom matnni o'zgarishsiz qaytaradi (chaqiruvchi
    `json.loads()` baribir xato beradi va tushunarli qayta ishlanadi)."""
    stripped = raw.strip()

    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        return fence_match.group(1)

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return stripped[first_brace : last_brace + 1]

    return stripped


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


class DwgElement(BaseModel):
    text: str = Field(min_length=1)
    x: float
    y: float
    layer: str


# Faza-45-topshiriq §B: bitta so'rovdagi elementlar soni chegaralanadi —
# xarajat/vaqt nazorati (kpgen tomonida ham chegaralanadi, bu — ikkinchi,
# server-tomon himoya qatlami, mijoz talabi).
_DWG_SPEC_MAX_ELEMENTS = 5000


class DwgSpecRequest(BaseModel):
    elements: list[DwgElement] = Field(min_length=1, max_length=_DWG_SPEC_MAX_ELEMENTS)


class DwgSpecPosition(BaseModel):
    naim: str = Field(min_length=1)
    ed: str = ""
    kol: float | None = None
    manba_matnlar: list[str] = Field(min_length=1)
    # Faza-45-topshiriq §B (haqiqiy xato #5, mijoz, 2026-09-08): "Поз."
    # ustunidagi pozitsiya belgisi (masalan "КЭ1", "В1") — kpgen tomonida
    # (`ai/dwg_ai.py`) qator chegarasini (band) aniqlash uchun ishlatiladi.
    # Yo'q/aniqlanmasa — null (bu pozitsiya keyin band-tekshiruvsiz rad
    # etiladi, "o'ylab topilgan" raqam bilan xato yasashdan ko'ra).
    belgi: str | None = None


class DwgSpecResponse(BaseModel):
    positions: list[DwgSpecPosition]


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


@app.post("/dwg_spec", response_model=DwgSpecResponse)
def dwg_spec(payload: DwgSpecRequest):
    """Faza-45-topshiriq §B: DXF'dan olingan xom matn+koordinata
    elementlaridan spetsifikatsiya jadvalini tiklaydi. Bu yerda FAQAT
    yengil format-tekshiruv (JSON to'g'ri, maydonlar bor) — manba-matn
    iqtiboslarining ASL elementlarga (matn VA koordinata bo'yicha)
    mosligini CHUQUR tekshirish kpgen tomonida (`ai/dwg_ai.py`),
    chunki faqat u ASL SvodRow modeliga yozish huquqiga ega."""
    elements_tsv = "\n".join(f"{e.text}\t{e.x:.1f}\t{e.y:.1f}\t{e.layer}" for e in payload.elements)
    _log.info("dwg_spec: %d element qabul qilindi", len(payload.elements))

    try:
        raw = ask_claude_dwg_spec(elements_tsv)
    except ProxyError as exc:
        _log.warning("dwg_spec: Anthropic chaqiruvi muvaffaqiyatsiz: %s", exc)
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    try:
        data = json.loads(_extract_json_object(raw))
        parsed = DwgSpecResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        _log.warning("dwg_spec: model javobi JSON/schema xato: %s", exc)
        return DwgSpecResponse(positions=[])

    _log.info("dwg_spec: %d pozitsiya qaytarilmoqda", len(parsed.positions))
    return parsed
