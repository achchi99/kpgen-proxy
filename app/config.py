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
