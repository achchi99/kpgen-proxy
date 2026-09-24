"""API kalitni /etc/kpgen-secrets.env'dan o'qish.

Kalit kodda, konfigda, git repo'da HECH QAYERDA yo'q — faqat serverdagi
shu faylda (root:root, 0600 huquq bilan tavsiya etiladi).
"""

import os
from pathlib import Path

SECRETS_FILE = Path(os.environ.get("KPGEN_SECRETS_FILE", "/etc/kpgen-secrets.env"))
MODEL_NAME = "claude-haiku-4-5"  # matn-klassifikatsiya (/classify)
# Vision (/vision) — CAD chizmasidagi vektor/qo'lyozma raqamlarni o'qish
# aniqroq model talab qiladi, shuning uchun alohida va environment
# orqali sozlanadigan (kodga qotirilmagan).
VISION_MODEL_NAME = os.environ.get("KPGEN_VISION_MODEL", "claude-sonnet-5")
# DWG spetsifikatsiya tiklash (/dwg_spec) — xom matn+koordinata ro'yxatidan
# jadval tiklash (Faza-45-topshiriq §B, mijoz, 2026-09-08) — vision bilan
# bir xil murakkablikda strukturaviy fikrlash talab qiladi.
DWG_SPEC_MODEL_NAME = os.environ.get("KPGEN_DWG_SPEC_MODEL", "claude-sonnet-5")
# Bitta DWG so'rovi uchun maksimal chiqish tokeni — juda uzun (o'ylab
# topilgan) javobning oldini oladi, xarajatni chegaralaydi.
#
# Jonli xato (mijoz, 2026-09-14, "900300...008.7" — matn-AI zaxira javobi
# 502 bilan kesilgan): 4096 KAM bo'lib chiqdi — aynan shu saboq (READ_
# SPEC_MAX_TOKENS'ning tarixiga qarang, pastda) endi bu yerga ham
# qo'llanildi, o'sha 16384'ga TENGLASHTIRILDI (matn-AI zaxira — dense
# GOST jadvali uchun oxirgi chora, read_spec bilan bir xil murakkablikda
# ko'p pozitsiyali javob berishi mumkin — kamroq qiymat tanlashga asos
# yo'q).
DWG_SPEC_MAX_TOKENS = int(os.environ.get("KPGEN_DWG_SPEC_MAX_TOKENS", "16384"))
# PDF/Excel sahifa-o'qish (/read_spec, Faza-72-topshiriq, mijoz,
# 2026-09-11) — rasm + matn birga (vision bilan bir xil murakkablikda,
# lekin bitta sahifada ko'p qator/bo'lim bo'lishi mumkin, shuning uchun
# max_tokens dwg_spec'dan kattaroq standart bilan).
READ_SPEC_MODEL_NAME = os.environ.get("KPGEN_READ_SPEC_MODEL", "claude-sonnet-5")
# Faza-72-topshiriq, 3-bosqich yakunidan keyingi tuzatish (mijoz,
# 2026-09-12): 8192 katta/zich Excel bo'laklar uchun YETARLI EMAS edi —
# model javobi kesilib, buzuq JSON'ga aylanardi (proxy buni AVVAL
# "hech narsa topilmadi" deb noto'g'ri talqin qilardi, endi main.py
# xato sifatida qaytaradi — pastga qarang). 16384'ga oshirildi, bo'lak
# hajmi HAM kichraytirildi (excel_qator_boluklariga_bol, kpgen
# repo'sida) — ikkalasi birga.
READ_SPEC_MAX_TOKENS = int(os.environ.get("KPGEN_READ_SPEC_MAX_TOKENS", "16384"))

# Faza-72, 4-bosqich (mijoz, 2026-09-12): AI shadow-rejimi production
# quvuriga ulanishidan OLDIN — kunlik xarajat chegarasi (real usage'dan
# hisoblanadi, /read_spec ostida). Yetganda /read_spec 429 qaytaradi
# (Anthropic'ga SO'ROV YUBORILMAYDI — xarajat aynan shu daqiqada
# to'xtaydi), kpgen tomoni buni "AI kunlik chegara" deb aniq talqin
# qilib, qoida yo'liga o'tadi. Xotirada saqlanadi (`kunlik_xarajat.py`) —
# `kpgen-proxy` xizmati `ProtectSystem=strict`/`ReadOnlyPaths` bilan
# ishlaydi, diskka yozish YO'Q (real production sinovida aniqlangan).
#
# Jonli xato (mijoz, 2026-09-14): $2/kun juda tor bo'lib chiqdi — bitta
# kunda 4 ta DWG fayl (ikkitasi muvaffaqiyatli, 301+96 qator) byudjetni
# tugatdi, keyingi ikkita fayl "AI kunlik xarajat chegarasiga yetildi"
# bilan rad etildi. Mijoz aniq ko'rsatmasi: "sifat birinchi, xarajat
# ikkinchi" (API'ga oyiga $20 to'laydi) — $2 dan $5 ga ko'tarildi.
AI_KUNLIK_XARAJAT_CHEGARA = float(os.environ.get("KPGEN_AI_KUNLIK_XARAJAT", "5.0"))


def _load_secrets_file(path: Path) -> None:
    """`/etc/kpgen-secrets.env` faylini (KEY=VALUE qatorlari, # izohlar
    o'tkazib yuboriladi) o'qib, hali o'rnatilmagan environment
    o'zgaruvchilarga yuklaydi. Fayl yo'q bo'lsa jimgina o'tkaziladi —
    masalan lokal ishga tushirishda ANTHROPIC_API_KEY allaqachon
    environment'da bo'lishi mumkin."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_secrets_file(SECRETS_FILE)


def get_api_key() -> str | None:
    """ANTHROPIC_API_KEY qiymatini qaytaradi, topilmasa None."""
    return os.environ.get("ANTHROPIC_API_KEY") or None


# Xavfsizlik-auditi topilmasi (mijoz, 2026-09-24, kpgen CLAUDE.md §48
# #8) — proxy endpoint'lari ilgari HECH QANDAY autentifikatsiya
# talab qilmasdi (loopback-bog'lanish — `--host 127.0.0.1` — yagona
# himoya qatlami edi, arxitektura qarzi). `KPGEN_PROXY_API_KEY` —
# `kpgen`(desktop/web)+`kpgen-proxy` orasidagi umumiy, qo'lda
# generatsiya qilingan maxfiy kalit (bir martalik `secrets.
# token_urlsafe(32)`), `/etc/kpgen-secrets.env`ga `ANTHROPIC_API_KEY`
# bilan bir qatorda qo'shiladi. **Sozlanmagan bo'lsa — tekshiruv
# NOOP** (`main.py::_require_api_key()`ga qarang) — bosqichma-bosqich
# deploy (kod avval, kalit keyin) xavfsiz bo'lishi uchun ATAYLAB shunday.
def get_proxy_api_key() -> str | None:
    """`KPGEN_PROXY_API_KEY` qiymatini qaytaradi, topilmasa None
    (bu holatda `_require_api_key()` tekshiruvni o'tkazib yuboradi)."""
    return os.environ.get("KPGEN_PROXY_API_KEY") or None
