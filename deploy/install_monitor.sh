#!/usr/bin/env bash
# kpgen-proxy monitoringini serverga o'rnatadi (qayta ishga tushirilsa zarar
# bermaydi — fayllar ustiga yoziladi, timer'lar qayta yoqiladi).
#
#   sudo bash deploy/install_monitor.sh
#
# Faqat sozlamani tekshirish (hech narsa o'rnatilmaydi, root shart emas):
#   KPGEN_MONITOR_ENV_FILE=/yo'l/fayl bash deploy/install_monitor.sh --check-env
set -euo pipefail

ENV_FILE="${KPGEN_MONITOR_ENV_FILE:-/etc/kpgen-monitor-secrets.env}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/monitor"
BIN_DIR=/opt/kpgen-proxy-monitor
UNIT_DIR=/etc/systemd/system
SERVICES=(kpgen-proxy-monitor.service kpgen-proxy-monitor-ai.service)
TIMERS=(kpgen-proxy-monitor.timer kpgen-proxy-monitor-ai.timer)

xato() { echo "XATO: $*" >&2; exit 1; }

qiymat() {  # qiymat KALIT — fayldagi oxirgi KALIT=... qiymati (qo'shtirnoqsiz)
    { grep -E "^[[:space:]]*$1=" "$ENV_FILE" || true; } | tail -n 1 | cut -d= -f2- | tr -d "\"' \r"
}

tekshir_env() {
    [ -f "$ENV_FILE" ] || xato "$ENV_FILE topilmadi. $SRC/kpgen-monitor-secrets.env.example namunasi bo'yicha yarating (chmod 600, root:root)."
    if [ -z "$(qiymat KPGEN_PROXY_API_KEY)" ]; then
        xato "$ENV_FILE ichida KPGEN_PROXY_API_KEY yo'q yoki bo'sh. /classify, /vision, /read_spec API-kalit talab qiladi — kalitsiz monitor har safar 401 oladi. /etc/kpgen-proxy-key.env dagi KPGEN_PROXY_API_KEY qiymatini '$ENV_FILE'ga 'KPGEN_PROXY_API_KEY=...' qatori sifatida qo'shing."
    fi
    for k in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
        [ -n "$(qiymat "$k")" ] || echo "OGOHLANTIRISH: $k bo'sh — monitor ogohlantirish yubora olmaydi (faqat journalctl'ga yozadi)." >&2
    done
    echo "Sozlama tekshiruvi: OK ($ENV_FILE, KPGEN_PROXY_API_KEY bor)"
}

if [ "${1:-}" = "--check-env" ]; then
    tekshir_env
    exit 0
fi

[ "$(id -u)" -eq 0 ] || xato "root kerak: sudo bash deploy/install_monitor.sh"
command -v systemctl >/dev/null || xato "systemctl topilmadi (systemd kerak)"
for f in check_proxy.py "${SERVICES[@]}" "${TIMERS[@]}"; do
    [ -f "$SRC/$f" ] || xato "$SRC/$f topilmadi — skriptni repo ichidan ishga tushiring"
done

tekshir_env

echo "== Fayllarni nusxalash"
install -D -m 0755 "$SRC/check_proxy.py" "$BIN_DIR/check_proxy.py"
for f in "${SERVICES[@]}" "${TIMERS[@]}"; do
    install -m 0644 "$SRC/$f" "$UNIT_DIR/$f"
done
install -d -m 0700 /var/lib/kpgen-proxy-monitor

echo "== systemd"
systemctl daemon-reload
systemctl enable "${TIMERS[@]}"
systemctl restart "${TIMERS[@]}"
systemd-analyze calendar '*-*-* 00/4:07:00' | sed -n '1,4p'
systemctl list-timers 'kpgen-proxy-monitor*' --no-pager

echo "== Birinchi yurish (haqiqiy chaqiruvlar, ~\$0.012)"
BOSHLANISH="$(date '+%Y-%m-%d %H:%M:%S')"
for s in "${SERVICES[@]}"; do
    systemctl start "$s" || echo "OGOHLANTIRISH: $s noldan farqli kod bilan tugadi" >&2
done
NATIJA="$(journalctl -u kpgen-proxy-monitor.service -u kpgen-proxy-monitor-ai.service --since "$BOSHLANISH" --no-pager -o cat)"
echo "$NATIJA"

if echo "$NATIJA" | grep -qE '^[a-z_]+: FAIL'; then
    echo "XATO: monitor endpoint'lardan birida muammo topdi (yuqoriga qarang). O'rnatish tugadi, lekin proxy/Anthropic tekshirilsin." >&2
    exit 2
fi
echo "Tayyor: o'rnatildi, endpoint'lar javob beryapti."
