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
