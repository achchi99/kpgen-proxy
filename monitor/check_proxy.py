#!/usr/bin/env python3
"""kpgen-proxy monitoring — HAQIQIY Anthropic ulanishini tekshiradi
(health emas — /health faqat jarayon tirikligini bildiradi, Anthropic
bilan real bog'lanishni EMAS — 2026-09-05dagi 3 kunlik sezilmagan
uzilish shu sababdan bo'lgan).

Uch endpoint tekshiriladi (komanda satri: `check_proxy.py [endpoint ...]`,
standart — `classify`):
- `classify`  — matn, `claude-haiku-4-5` (arzon, har 30 daqiqada);
- `vision`    — kichik sintetik PNG, `claude-sonnet-5`;
- `read_spec` — kichik sintetik PNG + 1 so'z, `claude-sonnet-5`
  (tizim-prompt + prompt-caching yo'li, ~$0.01/yurish — shuning uchun
  alohida, siyrakroq timer: 4 soatda bir marta).

/classify bilan /vision, /read_spec BIR XIL emas: model va so'rov
parametrlari farq qiladi, shu sababli faqat /classify tekshirilsa,
vision/read_spec uzilishi (model-parametr xatosi, 500) jim qolardi.
So'rov proxy'ning haqiqiy production yo'liga boradi — model va
parametrlar proxy tomonida belgilanadi, bu yerda takrorlanmaydi.

Tekshiriladi: HTTP 200 va javob TUZILISHI (mazmun to'g'riligi emas).

Ogohlantirish: har yurishda xato bo'lsa 60 s dan keyin BITTA qayta
urinish; ikkalasi ham yiqilsa — xabar (endpoint nomi, status kodi,
xato matnining sirsiz qisqartirilgan boshi). Keyin ALERT_INTERVAL_SEC
(standart 3 soat) da bir marta "hali ham buzuq" eslatmasi. Tuzalganda
— endpoint uchun bitta "TUZALDI". Kunlik AI limiti 429 si XATO EMAS:
kuniga bir marta ma'lumot xabari (monitor so'rovlari umumiy kunlik
hisobga kiradi — mijoz/Asror tasdig'i, variant A).
"""

import base64
import json
import os
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache

# Eski `KPGEN_PROXY_CHECK_URL` (to'liq /classify URL) ham qo'llab-quvvatlanadi.
_ESKI_URL = os.environ.get("KPGEN_PROXY_CHECK_URL")
BASE_URL = os.environ.get(
    "KPGEN_PROXY_BASE_URL",
    _ESKI_URL.rsplit("/", 1)[0] if _ESKI_URL else "http://127.0.0.1:8000",
).rstrip("/")
STATE_PATH = os.environ.get("KPGEN_MONITOR_STATE_PATH", "/var/lib/kpgen-proxy-monitor/state.json")
ALERT_INTERVAL_SEC = int(os.environ.get("KPGEN_MONITOR_ALERT_INTERVAL_SEC", 3 * 3600))
RETRY_DELAY_SEC = 60
TIMEOUT_SEC = {"classify": 20, "vision": 60, "read_spec": 60}
XATO_MATNI_UZUNLIGI = 200

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Jonli xato (mijoz, 2026-09-25): `/classify` §48 #8 bilan API-kalit
# talab qila boshlagach, bu monitor skript (kpgen/kpgen-proxy'dan
# TASHQARI, alohida server-skript) kalitsiz so'rov yuborib, har 30
# daqiqada 401 olib, soxta-ogohlantirish yuborardi. Sabab — deploy
# rejasi faqat worker+proxy unit'larini qamragan, bu skript
# hisobga olinmagan edi (CLAUDE.md §48'ga qarang).
PROXY_API_KEY = os.environ.get("KPGEN_PROXY_API_KEY")

# `kpgen-proxy/app/main.py::read_spec` shu iborani 429 matniga qo'yadi.
_KUNLIK_LIMIT_IBORASI = "kunlik xarajat chegarasi"

_SIR_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+|\d{6,}:[A-Za-z0-9_\-]{20,}")


# ---------------------------------------------------------------- sintetik PNG

# 5x7 bitmap shrift — faqat "1" va "2" (kerakli yagona matn "12").
_SHRIFT = {
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
}
_RASM_TOMON = 100
_MASSHTAB = 6
_BELGI_ORASI = 6
_MATN = "12"


def _matn_qutisi() -> tuple[int, int, int, int]:
    """Matnning rasmdagi chegarasi (x0, y0, x1, y1) — markazlashtirilgan."""
    eni = len(_MATN) * 5 * _MASSHTAB + (len(_MATN) - 1) * _BELGI_ORASI
    bo = 7 * _MASSHTAB
    x0 = (_RASM_TOMON - eni) // 2
    y0 = (_RASM_TOMON - bo) // 2
    return x0, y0, x0 + eni, y0 + bo


def _chunk(tur: bytes, malumot: bytes) -> bytes:
    govak = struct.pack(">I", len(malumot)) + tur + malumot
    return govak + struct.pack(">I", zlib.crc32(tur + malumot) & 0xFFFFFFFF)


@lru_cache(maxsize=1)
def sintetik_png() -> bytes:
    """100x100 kulrang PNG, oq fonda qora "12" — faqat stdlib (PIL yo'q)."""
    x0, y0, x1, y1 = _matn_qutisi()
    qatorlar = []
    for y in range(_RASM_TOMON):
        qator = bytearray([255] * _RASM_TOMON)
        if y0 <= y < y1:
            shrift_qator = (y - y0) // _MASSHTAB
            for i, belgi in enumerate(_MATN):
                bx = x0 + i * (5 * _MASSHTAB + _BELGI_ORASI)
                for k, katak in enumerate(_SHRIFT[belgi][shrift_qator]):
                    if katak == "#":
                        for dx in range(_MASSHTAB):
                            qator[bx + k * _MASSHTAB + dx] = 0
        qatorlar.append(b"\x00" + bytes(qator))  # filtr turi 0
    sarlavha = struct.pack(">IIBBBBB", _RASM_TOMON, _RASM_TOMON, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", sarlavha)
        + _chunk(b"IDAT", zlib.compress(b"".join(qatorlar), 9))
        + _chunk(b"IEND", b"")
    )


def sintetik_png_base64() -> str:
    return base64.b64encode(sintetik_png()).decode("ascii")


# ----------------------------------------------------------- endpoint ta'riflari

def _classify_tana() -> dict:
    return {"text": "ping"}


def _vision_tana() -> dict:
    return {"image_base64": sintetik_png_base64(), "context": "monitoring: sintetik test katagi"}


def _read_spec_tana() -> dict:
    x0, y0, x1, y1 = _matn_qutisi()
    return {
        "image_base64": sintetik_png_base64(),
        "sozlar": [{"id": "w1", "matn": _MATN, "x0": x0, "y0": y0, "x1": x1, "y1": y1}],
        "sahifa_raqami": 1,
    }


def _classify_tuzilma(p) -> str | None:
    return None if isinstance(p, dict) and p.get("category") else "javobda 'category' yo'q"


def _vision_tuzilma(p) -> str | None:
    if isinstance(p, dict) and "value" in p and p.get("confidence") in ("high", "low"):
        return None
    return "javob tuzilishi noto'g'ri (value/confidence)"


def _read_spec_tuzilma(p) -> str | None:
    if isinstance(p, dict) and p.get("sahifa") == 1 and isinstance(p.get("bolimlar"), list):
        return None
    return "javob tuzilishi noto'g'ri (sahifa/bolimlar)"


ENDPOINTLAR = {
    "classify": ("/classify", _classify_tana, _classify_tuzilma),
    "vision": ("/vision", _vision_tana, _vision_tuzilma),
    "read_spec": ("/read_spec", _read_spec_tana, _read_spec_tuzilma),
}


# ------------------------------------------------------------------ yordamchilar

def sirlarni_yashir(matn: str) -> str:
    """Xato matnidan sirlarni niqoblaydi (Anthropic kaliti, bot-token va
    shu skriptga berilgan aniq kalit qiymatlari)."""
    matn = _SIR_RE.sub("***", matn)
    for sir in (PROXY_API_KEY, TELEGRAM_TOKEN, os.environ.get("ANTHROPIC_API_KEY")):
        if sir and len(sir) >= 6:
            matn = matn.replace(sir, "***")
    return matn


def _qisqa(matn: str) -> str:
    return sirlarni_yashir(matn)[:XATO_MATNI_UZUNLIGI]


def _bugun() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _bosh_holat() -> dict:
    return {"endpoints": {}, "limit_xabari": {}}


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _bosh_holat()
    if not isinstance(data, dict):
        return _bosh_holat()
    if "endpoints" not in data:  # eski format: {"status", "last_alert_at"} — faqat /classify
        eski = {"status": data.get("status", "ok"), "last_alert_at": data.get("last_alert_at", 0)}
        return {"endpoints": {"classify": eski}, "limit_xabari": {}}
    data.setdefault("limit_xabari", {})
    return data


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


@contextmanager
def _qulf():
    """Ikki timer bir vaqtda holat faylini yozmasin (faqat Linux; boshqa
    tizimda — qulfsiz)."""
    try:
        import fcntl
    except ImportError:
        yield
        return
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH + ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def send_telegram(text: str) -> bool:
    """Yuborildi — True. Sozlanmagan yoki xato — False (skript qulamaydi)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID sozlanmagan — xabar yuborilmadi",
            file=sys.stderr,
        )
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as exc:  # noqa: BLE001 — monitoring skripti hech qachon qulamasin
        print(f"Telegram xabar yuborilmadi: {sirlarni_yashir(str(exc))}", file=sys.stderr)
        return False


# --------------------------------------------------------------------- tekshiruv

def check_endpoint(nom: str) -> tuple[str, str | None]:
    """("ok" | "limit" | "fail", sabab). "limit" — kunlik AI limiti (429),
    xato EMAS."""
    yol, tana_qur, tuzilma_tekshir = ENDPOINTLAR[nom]
    headers = {"Content-Type": "application/json"}
    if PROXY_API_KEY:
        headers["X-KPGen-Api-Key"] = PROXY_API_KEY
    req = urllib.request.Request(
        BASE_URL + yol, data=json.dumps(tana_qur()).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC[nom]) as resp:
            if resp.status != 200:
                return "fail", f"HTTP {resp.status}"
            try:
                payload = json.loads(resp.read())
            except json.JSONDecodeError:
                return "fail", "HTTP 200 — javob JSON emas"
            xato = tuzilma_tekshir(payload)
            return ("ok", None) if xato is None else ("fail", f"HTTP 200 — {xato}")
    except urllib.error.HTTPError as exc:
        try:
            tana = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            tana = ""
        if exc.code == 429 and _KUNLIK_LIMIT_IBORASI in tana:
            return "limit", None
        return "fail", f"HTTP {exc.code} — {_qisqa(tana)}"
    except urllib.error.URLError as exc:
        return "fail", f"ulanish xatosi: {_qisqa(str(exc.reason))}"
    except Exception as exc:  # noqa: BLE001
        return "fail", f"kutilmagan xato: {_qisqa(str(exc))}"


def check_with_retry(nom: str) -> tuple[str, str | None]:
    """Xato bo'lsa RETRY_DELAY_SEC dan keyin BITTA qayta urinish."""
    natija = check_endpoint(nom)
    if natija[0] == "fail":
        time.sleep(RETRY_DELAY_SEC)
        natija = check_endpoint(nom)
    return natija


def _yangilash(nom: str, state: dict, natija: tuple[str, str | None], now: float) -> str:
    holat, sabab = natija
    es = state["endpoints"].setdefault(nom, {"status": "ok", "last_alert_at": 0})
    yol = ENDPOINTLAR[nom][0]

    if holat == "ok":
        if es.get("status") == "fail":
            if send_telegram(f"kpgen-proxy: TUZALDI — {yol} tiklandi."):
                es.update(status="ok", last_alert_at=0)
        else:
            es.update(status="ok", last_alert_at=0)
        return "OK"

    if holat == "limit":
        bugun = _bugun()
        if state["limit_xabari"].get(nom) != bugun:
            if send_telegram(f"kpgen-proxy: kunlik AI limiti tugadi, {yol} bugun ishlamaydi"):
                state["limit_xabari"][nom] = bugun
        return "LIMIT (kunlik AI limiti — xato emas)"

    since_last_alert = now - es.get("last_alert_at", 0)
    if es.get("status") != "fail" or since_last_alert >= ALERT_INTERVAL_SEC:
        if send_telegram(f"kpgen-proxy: XATO — {yol}: {sabab}"):
            es["last_alert_at"] = now
    es["status"] = "fail"
    return f"FAIL: {sabab}"


def main(argv: list[str] | None = None) -> None:
    nomlar = list(sys.argv[1:] if argv is None else argv) or ["classify"]
    nomalum = [n for n in nomlar if n not in ENDPOINTLAR]
    if nomalum:
        print(f"noma'lum endpoint: {', '.join(nomalum)} (mumkin: {', '.join(ENDPOINTLAR)})", file=sys.stderr)
        sys.exit(64)

    with _qulf():
        state = load_state()
        for nom in nomlar:
            natija = check_with_retry(nom)
            print(f"{nom}: {_yangilash(nom, state, natija, time.time())}")
        save_state(state)


if __name__ == "__main__":
    main()
