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

from datetime import datetime, timezone

from app.config import AI_KUNLIK_XARAJAT_CHEGARA

NARX_KIRISH = 2.00
NARX_CHIQISH = 10.00
NARX_CACHE_READ = 0.20

_holat = {"sana": None, "jami_dollar": 0.0}


def usage_narxi(usage: dict) -> float:
    return (
        usage.get("input_tokens", 0) / 1_000_000 * NARX_KIRISH
        + usage.get("output_tokens", 0) / 1_000_000 * NARX_CHIQISH
        + usage.get("cache_read_input_tokens", 0) / 1_000_000 * NARX_CACHE_READ
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
