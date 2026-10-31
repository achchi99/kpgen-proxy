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

## `/loyiha_tavsiya` (kpgen A8a — «Проект вентиляции»)

Xona vazifasi (matn) va sanuzel jihozlari (xona kesimi rasmi) bo'yicha AI TAKLIFI — kpgen
`kpgen/ai/xona_tavsiya.py` klienti bilan kontrakt (`app/loyiha_tavsiya.py` docstring'i):

| `vazifa` | Kirish | Javob |
|---|---|---|
| `xona_vazifasi` | `xona_nomi`, `variantlar: [{kalit, nomi}]` | `{vazifa: kalit\|null, dalil, narx}` |
| `sanuzel_jihozlari` | `xona_nomi`, `jihozlar`, `image_base64` (PNG/JPEG) | `{jihozlar: {unitaz\|vanna\|dush\|rakovina: {holat: topildi\|yoq\|nomalum, joy: [x,y]\|null}}, narx}` |

Model — `KPGEN_TAVSIYA_MODEL` (sukut `claude-sonnet-5`; so'rovdagi `model` e'tiborsiz), javob — majburiy
tool-chaqiruv, server sxemasi bilan tekshiriladi (mos emas — 502). Noma'lum `vazifa` — 400, rasm > 2 MB yoki
> 2000 px — 413, kunlik limit — 429, Anthropic timeout — 504. Rasm va xona nomi saqlanmaydi, logga yozilmaydi
(logda: vazifa, holat, hajm, narx, davomiylik).

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
200 qaytargani uchun sezilmagan). `monitor/check_proxy.py` haqiqiy
so'rov yuboradi:

| Endpoint | Model | Chastota | Taxminiy narx |
|---|---|---|---|
| `/classify` | haiku | har 30 daqiqa (`kpgen-proxy-monitor.timer`) | ~0 |
| `/vision`, `/read_spec` | sonnet (sintetik 100x100 PNG) | har 4 soat, 00:07, 04:07, ... (`kpgen-proxy-monitor-ai.timer`) | ~$0.012/yurish, ~$0.07/kun |

Tekshiriladi: HTTP 200 va javob tuzilishi (mazmun emas). Xato bo'lsa 60 s
dan keyin bitta qayta urinish; ikkalasi ham yiqilsa Telegram xabari
(endpoint, status kodi, sirsiz qisqa xato matni), keyin har 3 soatda
eslatma, tuzalganda "TUZALDI". Kunlik AI limiti 429 si xato emas — kuniga
bir marta ma'lumot xabari (monitor so'rovlari umumiy kunlik hisobga kiradi).

O'rnatish (server, root): `/etc/kpgen-monitor-secrets.env` ni
`monitor/kpgen-monitor-secrets.env.example` bo'yicha yarating
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `KPGEN_PROXY_API_KEY`; `chmod 600`),
so'ng:

```bash
sudo bash deploy/install_monitor.sh
```

Skript qayta ishga tushirilsa zarar bermaydi; `KPGEN_PROXY_API_KEY` yo'q
bo'lsa aniq xato bilan to'xtaydi; oxirida birinchi yurishni bajarib
natijani ko'rsatadi. Sozlamani o'rnatmasdan tekshirish:
`bash deploy/install_monitor.sh --check-env`.
