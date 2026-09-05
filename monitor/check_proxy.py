#!/usr/bin/env python3
"""kpgen-proxy monitoring — HAQIQIY Anthropic ulanishini tekshiradi
(health emas — /health faqat jarayon tirikligini bildiradi, Anthropic
bilan real bog'lanishni EMAS — 2026-09-05dagi 3 kunlik sezilmagan
uzilish shu sababdan bo'lgan).

/classify endpointi ishlatiladi (/vision emas) — ikkalasi ham bir xil
`_call_anthropic()` orqali o'tadi (kpgen-proxy/app/anthropic_client.py),
shuning uchun /classify bilan tekshirish arzon/tez, lekin xuddi shu
auth/tarmoq xatolarini ushlaydi.

Ketma-ket xato holatida FAQAT bitta xabar (birinchi aniqlanganda),
keyin ALERT_INTERVAL_SEC (standart 3 soat) da bir marta "hali ham
buzuq" eslatmasi. Tuzalganda — bitta "tuzaldi" xabari.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

PROXY_URL = os.environ.get("KPGEN_PROXY_CHECK_URL", "http://127.0.0.1:8000/classify")
STATE_PATH = os.environ.get("KPGEN_MONITOR_STATE_PATH", "/var/lib/kpgen-proxy-monitor/state.json")
ALERT_INTERVAL_SEC = int(os.environ.get("KPGEN_MONITOR_ALERT_INTERVAL_SEC", 3 * 3600))
TIMEOUT_SEC = 20

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"status": "ok", "last_alert_at": 0}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(
            "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID sozlanmagan — xabar yuborilmadi",
            file=sys.stderr,
        )
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:  # noqa: BLE001 — monitoring skripti hech qachon qulamasin
        print(f"Telegram xabar yuborilmadi: {exc}", file=sys.stderr)


def check_proxy() -> tuple[bool, str | None]:
    body = json.dumps({"text": "ping"}).encode("utf-8")
    req = urllib.request.Request(PROXY_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            payload = json.loads(resp.read())
            if not payload.get("category"):
                return False, "javobda 'category' yo'q"
            return True, None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return False, f"HTTP {exc.code}: {detail}"
    except urllib.error.URLError as exc:
        return False, f"ulanish xatosi: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, f"kutilmagan xato: {exc}"


def main() -> None:
    ok, reason = check_proxy()
    state = load_state()
    now = time.time()

    if ok:
        if state.get("status") == "fail":
            send_telegram("kpgen-proxy: TUZALDI — Anthropic bilan bog'lanish tiklandi.")
        save_state({"status": "ok", "last_alert_at": 0})
        print("OK")
        return

    since_last_alert = now - state.get("last_alert_at", 0)
    if state.get("status") != "fail" or since_last_alert >= ALERT_INTERVAL_SEC:
        send_telegram(f"kpgen-proxy: XATO — Anthropic bilan bog'lanib bo'lmadi ({reason}).")
        state["last_alert_at"] = now
    state["status"] = "fail"
    save_state(state)
    print(f"FAIL: {reason}")


if __name__ == "__main__":
    main()
