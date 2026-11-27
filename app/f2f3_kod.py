"""`POST /f2f3_kod` — kpgen Ф-2/Ф-3: КП qatoriga норма KODI TAKLIFI (klient `kpgen/ai/f2f3_kod.py`, 27.11.2026).

Qoida yo'li tanlay olmagan qatorlar uchun model nomzodlar ro'yxatidan BITTA kod taklif qiladi yoki `null` («нормы нет»).
Model kod to'qimaydi va hisob qilmaydi; kpgen kodni nomzodlarga qarshi o'zi ham tekshiradi va foydalanuvchi
«Принять» bosmaguncha hech narsa o'zgarmaydi. Kontrakt (kpgen klienti bilan AYNAN):

  {vazifa: "f2f3_kod", bosqich: "jadval"|"variant", model, prompt_versiya, sxema_versiya,
   umumiy_nomzodlar: [{kod, nom, birlik}],            # faqat «jadval» (~1100 ta, prompt-keshlanadi)
   qatorlar: [{id, nom, birlik, nomzodlar: [{kod, nom, birlik}]}]}   # nomzodlar — faqat «variant»; ≤ 25 qator
  → {"javoblar": [{"id", "kod": str|null, "sabab": str ≤ 240}], "narx": $}

Maxfiylik: qator nomlari/kodlar logga YOZILMAYDI — faqat hajm, qator/javob soni, narx, davomiylik, holat."""

import json
import logging
import re
import time
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import anthropic_client, config, kunlik_xarajat
from app.anthropic_client import ProxyError

_log = logging.getLogger("kpgen_proxy")

router = APIRouter()

MAX_QATOR = 25
SABAB_MAX = 240
_MAX_UMUMIY = 3000      # ~1100 kutiladi; yuqori chegara — xarajat/hajm himoyasi (oshsa 400)
_MAX_NOMZOD = 200       # bitta qatorning variantlari

_SYSTEM = (
    "Ты — сметчик. Для каждой строки коммерческого предложения выбери ОДНУ норму из списка кандидатов, по которой\n"
    "выполняется МОНТАЖ этой позиции, или верни null, если подходящей нормы в списке нет. Нельзя выдумывать коды:\n"
    "\"kod\" — только точная строка из списка кандидатов этой строки (или общего списка). Учитывай тип изделия, размер,\n"
    "материал и единицу измерения. \"sabab\" — одно короткое предложение по-русски (почему эта норма или почему нет).\n"
    "Ответ — только JSON: {\"javoblar\": [{\"id\": \"...\", \"kod\": \"...\" | null, \"sabab\": \"...\"}]}."
)


class Nomzod(BaseModel):
    kod: str = Field(min_length=1, max_length=60)
    nom: str = Field(default="", max_length=600)
    birlik: str = Field(default="", max_length=30)


class Qator(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    nom: str = Field(default="", max_length=600)
    birlik: str = Field(default="", max_length=30)
    nomzodlar: list[Nomzod] = Field(default_factory=list, max_length=_MAX_NOMZOD)


class KodRequest(BaseModel):
    vazifa: str
    bosqich: Literal["jadval", "variant"]
    model: str | None = None
    prompt_versiya: str | None = None
    sxema_versiya: int | None = None
    umumiy_nomzodlar: list[Nomzod] = Field(default_factory=list)
    qatorlar: list[Qator] = Field(min_length=1)       # ≤ 25 — qo'lda (400), pydantic 422 bermasin


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _json_ol(xom: str):
    """Model matnidan JSON obyektini oladi (``` o'rami olib tashlanadi). Parse bo'lmasa — ValueError."""
    s = xom.strip()
    m = _FENCE.search(s)
    if m:
        s = m.group(1)
    else:
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b > a:
            s = s[a:b + 1]
    return json.loads(s)


def _javoblarni_tekshir(data, idlar: set[str]) -> list[dict]:
    """id so'rovdagi id; kod — null yoki satr; sabab — satr ≤ 240. Noto'g'ri element TASHLANADI (takror id — birinchisi).
    Kodni nomzodlarga qarshi tekshirish — kpgen tomonida (faqat u qaror qiladi)."""
    if not isinstance(data, dict) or not isinstance(data.get("javoblar"), list):
        raise ValueError("«javoblar» ro'yxati yo'q")
    chiqish, korilgan = [], set()
    for j in data["javoblar"]:
        if not isinstance(j, dict):
            continue
        id_, kod, sabab = j.get("id"), j.get("kod"), j.get("sabab")
        if not isinstance(id_, str) or id_ not in idlar or id_ in korilgan:
            continue
        if kod is not None and not isinstance(kod, str):
            continue
        if not isinstance(sabab, str) or len(sabab) > SABAB_MAX:
            continue
        korilgan.add(id_)
        chiqish.append({"id": id_, "kod": kod, "sabab": sabab})
    return chiqish


def _xato(status: int, matn: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": matn})


def _satr(n: Nomzod) -> str:
    return f"{n.kod} | {n.nom} | {n.birlik}"


@router.post("/f2f3_kod")
def f2f3_kod(payload: KodRequest):
    t0 = time.monotonic()
    hajm = len(payload.model_dump_json().encode())

    def tugat(javob, javob_soni: int = 0, narx: float = 0.0):
        holat = javob.status_code if isinstance(javob, JSONResponse) else 200
        _log.info("f2f3_kod: holat=%d bosqich=%s qator=%d javob=%d hajm=%d narx=$%.5f davomiylik=%.2fs",
                  holat, payload.bosqich, len(payload.qatorlar), javob_soni, hajm, narx, time.monotonic() - t0)
        return javob

    if payload.vazifa != "f2f3_kod":
        return tugat(_xato(400, "неизвестная vazifa (f2f3_kod)"))
    model = payload.model or config.F2F3_KOD_MODEL_NAME
    if model not in config.F2F3_KOD_RUXSAT_MODELLAR:
        return tugat(_xato(400, "model не разрешён"))
    if len(payload.qatorlar) > MAX_QATOR:
        return tugat(_xato(400, f"qatorlar: не более {MAX_QATOR} строк за запрос"))
    idlar = [q.id for q in payload.qatorlar]
    if len(set(idlar)) != len(idlar):
        return tugat(_xato(422, "qatorlar: id повторяются"))
    if payload.bosqich == "jadval":
        if not payload.umumiy_nomzodlar or len(payload.umumiy_nomzodlar) > _MAX_UMUMIY:
            return tugat(_xato(400, f"umumiy_nomzodlar: нужно 1..{_MAX_UMUMIY} записей для bosqich=jadval"))
    elif any(not q.nomzodlar for q in payload.qatorlar):
        return tugat(_xato(400, "nomzodlar: для bosqich=variant у каждой строки нужны кандидаты"))

    if kunlik_xarajat.chegaraga_yetdimi():
        return tugat(_xato(429, "AI kunlik xarajat chegarasiga yetildi — ertaga qayta urinib ko'ring"))

    if payload.bosqich == "jadval":
        qatorlar = [{"id": q.id, "nom": q.nom, "birlik": q.birlik} for q in payload.qatorlar]
        content = [
            # umumiy ro'yxat har so'rovda bir xil (~30k token) — prompt caching
            {"type": "text", "text": "Общий список таблиц норм (kod | nom | birlik):\n"
             + "\n".join(_satr(n) for n in payload.umumiy_nomzodlar), "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Строки:\n" + json.dumps(qatorlar, ensure_ascii=False)},
        ]
    else:
        qatorlar = [{"id": q.id, "nom": q.nom, "birlik": q.birlik,
                     "nomzodlar": [n.model_dump() for n in q.nomzodlar]} for q in payload.qatorlar]
        content = [{"type": "text", "text": "Строки:\n" + json.dumps(qatorlar, ensure_ascii=False)}]

    try:
        xom, usage = anthropic_client.ask_claude_matn(
            model=model, system=_SYSTEM, content=content,
            max_tokens=config.F2F3_KOD_MAX_TOKENS, timeout=config.F2F3_KOD_TIMEOUT)
    except ProxyError as exc:
        return tugat(_xato(exc.status_code, str(exc)))

    narx = round(kunlik_xarajat.usage_narxi(usage), 6) if usage else 0.0
    if usage:
        kunlik_xarajat.qoshish(usage)
    try:
        javoblar = _javoblarni_tekshir(_json_ol(xom), set(idlar))
    except ValueError as exc:     # json.JSONDecodeError ham ValueError
        _log.warning("f2f3_kod: model javobi JSON/sxema xato: %s", exc)
        return tugat(_xato(502, f"Model javobi JSON sifatida buzuq: {exc}"), 0, narx)
    return tugat({"javoblar": javoblar, "narx": narx}, len(javoblar), narx)
