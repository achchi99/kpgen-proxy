# kpgen-proxy

kpgen desktop dasturi uchun VPS proxy — Anthropic API kalitini
mijozning kompyuteridan yashiradi (CLAUDE.md §6: "API kalit dasturda,
konfigda, kodda YO'Q — faqat VPS'da").

## Lokal ishga tushirish

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # yoki /etc/kpgen-secrets.env yarating
uvicorn app.main:app --reload
```

Tekshirish:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/classify \
     -H "Content-Type: application/json" \
     -d '{"text": "Дроссель-клапан 300x200"}'
```

`/vision` — CAD chizmasidagi vektor/qo'lyozma raqamni o'qiydi (kesilgan
katak-rasm, base64):

```bash
curl -X POST http://127.0.0.1:8000/vision \
     -H "Content-Type: application/json" \
     -d "{\"image_base64\": \"$(base64 -w0 cell.png)\", \"context\": \"Кол-во, 500x150\"}"
```

## Testlar

```bash
pytest tests/ -v
```

Testlar HAQIQIY tarmoqqa chiqmaydi (`ask_claude`/`ask_claude_vision`
mock qilinadi) — API kalit talab qilinmaydi, xarajatsiz.

## Serverga o'rnatish (systemd)

1. Loyihani `/opt/kpgen-proxy`ga nusxalang, venv yarating, `pip install -r requirements.txt`.
2. `.env.example` namunasi bo'yicha `/etc/kpgen-secrets.env` yarating
   (`chmod 600`, `chown root:root`), haqiqiy `ANTHROPIC_API_KEY` bilan.
3. Servis foydalanuvchisi yarating: `useradd --system --no-create-home kpgen-proxy`.
4. `kpgen-proxy.service`ni `/etc/systemd/system/`ga nusxalang.
5.
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now kpgen-proxy
   sudo systemctl status kpgen-proxy
   ```

Server qayta ishga tushsa, `enable` tufayli proxy o'zi qayta ko'tariladi.
Ishlab chiqarishda `127.0.0.1:8000` oldiga nginx/reverse-proxy (TLS
bilan) qo'yish tavsiya etiladi — bu fayl buni o'z ichiga olmaydi.

## Monitoring (Telegram xabarnoma)

`/health` faqat jarayon tirikligini bildiradi — Anthropic bilan real
bog'lanishni EMAS (2026-09-05: proxy 3 kun ishlamay turgan, health esa
200 qaytargani uchun sezilmagan). `monitor/` papkasi buni tuzatadi:
har 30 daqiqada `/classify`ga haqiqiy so'rov yuboradi (bu `/vision`
bilan bir xil `_call_anthropic()` orqali o'tadi, shuning uchun arzon
matn-so'rov bilan ham real Anthropic-ulanish tekshiriladi). Ketma-ket
xatoda faqat birinchi aniqlanganda va keyin har 3 soatda bitta xabar
(spam emas), tuzalganda bitta "tuzaldi" xabari.

O'rnatish:

1. `monitor/check_proxy.py` → `/opt/kpgen-proxy-monitor/check_proxy.py`
2. `monitor/kpgen-proxy-monitor.service` va `.timer` →
   `/etc/systemd/system/`
3. `monitor/kpgen-monitor-secrets.env.example` namunasi bo'yicha
   `/etc/kpgen-monitor-secrets.env` yarating (`chmod 600 root:root`),
   `TELEGRAM_BOT_TOKEN` va `TELEGRAM_CHAT_ID` bilan
4.
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now kpgen-proxy-monitor.timer
   sudo systemctl list-timers kpgen-proxy-monitor.timer
   ```

Qo'lda sinash: `sudo systemctl start kpgen-proxy-monitor.service` (natija
`journalctl -u kpgen-proxy-monitor.service -n 20`da ko'rinadi).
