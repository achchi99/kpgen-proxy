"""Faza-72, 4-bosqich (mijoz, 2026-09-12) — AI kunlik xarajat nazorati.

Diskka (`AI_KUNLIK_HOLAT_FAYL`) kunlik (server sanasi bo'yicha) jami
dollar-xarajatni saqlaydi — proxy qayta ishga tushsa ham (deploy)
yo'qolmaydi. Bitta uvicorn worker, past trafik (bitta ichki mijoz)
uchun mo'ljallangan — parallel yozuvlar orasidagi poyga holati
(race condition) ATAYLAB e'tiborsiz qoldirilgan (oddiy o'qi-yoz,
fayl-qulf YO'Q); agar kelajakda ko'p worker/parallel trafik bo'lsa,
bu qatъiylashtirilishi kerak bo'ladi.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.config import AI_KUNLIK_HOLAT_FAYL, AI_KUNLIK_XARAJAT_CHEGARA

NARX_KIRISH = 2.00
NARX_CHIQISH = 10.00
NARX_CACHE_READ = 0.20


def usage_narxi(usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) / 1_000_000 * NARX_KIRISH
        + usage.get("output_tokens", 0) / 1_000_000 * NARX_CHIQISH
        + usage.get("cache_read_input_tokens", 0) / 1_000_000 * NARX_CACHE_READ
    )


def _bugun() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _oqi(fayl: Path) -> dict:
    if not fayl.is_file():
        return {"sana": _bugun(), "jami_dollar": 0.0}
    try:
        holat = json.loads(fayl.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"sana": _bugun(), "jami_dollar": 0.0}
    if holat.get("sana") != _bugun():
        return {"sana": _bugun(), "jami_dollar": 0.0}
    return holat


def _yoz(fayl: Path, holat: dict) -> None:
    fayl.parent.mkdir(parents=True, exist_ok=True)
    fayl.write_text(json.dumps(holat, ensure_ascii=False), encoding="utf-8")


def bugungi_xarajat(fayl: Path = AI_KUNLIK_HOLAT_FAYL) -> float:
    """Bugungi (UTC sanasi bo'yicha) jami xarajat — sana o'zgarsa 0'dan
    boshlanadi (avtomatik, `_oqi()` ichida)."""
    return _oqi(fayl)["jami_dollar"]


def chegaraga_yetdimi(fayl: Path = AI_KUNLIK_HOLAT_FAYL, chegara: float = AI_KUNLIK_XARAJAT_CHEGARA) -> bool:
    return bugungi_xarajat(fayl) >= chegara


def qoshish(usage: dict, *, fayl: Path = AI_KUNLIK_HOLAT_FAYL) -> float:
    """Bitta so'rovning narxini bugungi jamiga qo'shadi, YANGI jami
    xarajatni qaytaradi."""
    holat = _oqi(fayl)
    holat["jami_dollar"] = holat["jami_dollar"] + usage_narxi(usage)
    _yoz(fayl, holat)
    return holat["jami_dollar"]
