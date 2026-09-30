"""Faza-72, 4-bosqich (mijoz, 2026-09-12) — AI kunlik xarajat nazorati.

Xotirada (modul darajasidagi global) — kunlik (server sanasi bo'yicha)
jami dollar-xarajatni saqlaydi. Diskka YOZILMAYDI: `kpgen-proxy`
systemd xizmati `ProtectSystem=strict` + `ReadOnlyPaths=/opt/kpgen-
proxy` bilan ishga tushiriladi (ataylab, xavfsizlik uchun) — bu
papkaning O'ZI (yoki tag'in bir joy, `ReadWritePaths=` YO'Q) hech
qanday fayl yozishga ruxsat bermaydi. Diskka yozish real production
sinovida (2026-09-12) "[Errno 30] Read-only file system" bilan
ANIQLANGAN, xotira-asosli yechimga o'tildi.

OQIBAT (ataylab qabul qilingan chegara): proxy qayta ishga tushsa
(har deploy) — kunlik hisoblagich 0'dan boshlanadi. Bitta ichki
mijoz, kam trafik uchun bu qabul qilinadi — deploy ko'p marta
sodir bo'lmaydi, va $2/kun chegarasi baribir "qo'pol" himoya
(aniq byudjet emas). Kelajakda buni istisno qilish kerak bo'lsa —
`ReadWritePaths=` systemd unit fayliga qo'shilishi (root/sudo talab
qiladi) va bu modul qaytadan fayl-asosli qilinishi kerak bo'ladi."""

import json
import os
import re
from datetime import datetime, timezone

from app.config import AI_KUNLIK_XARAJAT_CHEGARA

# Model bo'yicha narx jadvali (USD / 1M token): (kirish, chiqish, kesh-o'qish,
# kesh-yozish). Kesh YOZISH (ephemeral/5-daqiqalik TTL) bazaviy kirish
# narxidan 1.25x qimmat — Codex/mijoz topgan teshik (2026-09-12): ilgari
# bu kunlik xarajat hisobiga UMUMAN kirmasdi.
# claude-sonnet-5-5: mijoz Console'dan tasdiqlagan (2026-09-30).
NARXLAR: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-5": (2.00, 10.00, 0.20, 2.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
}
# Model KO'RSATILMAGAN usage (eski chaqiruvchilar/testlar) — avvalgi standart.
STANDART_MODEL = "claude-sonnet-5"
# Jadvalda YO'Q model — XAVFLI (qimmat) narx: byudjet kamroq emas, ko'proq
# hisoblansin (chegara erta ishga tushadi, jimgina oshib ketmaydi).
NOMALUM_MODEL_NARXI = (15.00, 75.00, 1.50, 18.75)

# Muhit orqali qo'shimcha/almashtirilgan narx: KPGEN_MODEL_NARXLAR=
# '{"model-nomi": [kirish, chiqish, kesh_oqish, kesh_yozish]}'
_ENV_NARXLAR = os.environ.get("KPGEN_MODEL_NARXLAR", "").strip()
if _ENV_NARXLAR:
    try:
        for _m, _n in json.loads(_ENV_NARXLAR).items():
            NARXLAR[_m] = tuple(float(x) for x in _n)  # type: ignore[assignment]
    except (ValueError, TypeError, AttributeError):
        pass  # buzuq env — jadval o'zgarishsiz qoladi (xavfsiz)

_SANA_QOSHIMCHASI = re.compile(r"-\d{8}$")


def model_narxi(model: str | None) -> tuple[float, float, float, float]:
    """Model bo'yicha narx; noma'lum model — xavfsiz (qimmat) narx."""
    if not model:
        model = STANDART_MODEL
    if model in NARXLAR:
        return NARXLAR[model]
    asos = _SANA_QOSHIMCHASI.sub("", model)  # "...-20251001" qo'shimchasi
    return NARXLAR.get(asos, NOMALUM_MODEL_NARXI)


_holat = {"sana": None, "jami_dollar": 0.0}


def usage_narxi(usage: dict) -> float:
    n_kirish, n_chiqish, n_oqish, n_yozish = model_narxi(usage.get("model"))
    return (
        usage.get("input_tokens", 0) / 1_000_000 * n_kirish
        + usage.get("output_tokens", 0) / 1_000_000 * n_chiqish
        + usage.get("cache_read_input_tokens", 0) / 1_000_000 * n_oqish
        + usage.get("cache_creation_input_tokens", 0) / 1_000_000 * n_yozish
    )


def _bugun() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _joriy_holat() -> dict:
    if _holat["sana"] != _bugun():
        _holat["sana"] = _bugun()
        _holat["jami_dollar"] = 0.0
    return _holat


def bugungi_xarajat() -> float:
    """Bugungi (UTC sanasi bo'yicha) jami xarajat — sana o'zgarsa 0'dan
    boshlanadi (avtomatik)."""
    return _joriy_holat()["jami_dollar"]


def chegaraga_yetdimi(chegara: float = AI_KUNLIK_XARAJAT_CHEGARA) -> bool:
    return bugungi_xarajat() >= chegara


def qoshish(usage: dict) -> float:
    """Bitta so'rovning narxini bugungi jamiga qo'shadi, YANGI jami
    xarajatni qaytaradi."""
    holat = _joriy_holat()
    holat["jami_dollar"] += usage_narxi(usage)
    return holat["jami_dollar"]
