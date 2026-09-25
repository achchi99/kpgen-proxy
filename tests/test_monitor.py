"""`monitor/check_proxy.py` — throttling/holat mantig'i, HAQIQIY
tarmoqqa yoki Telegramga chiqmasdan (`urllib.request.urlopen` mock)."""

import json
from unittest.mock import MagicMock, patch

from monitor import check_proxy


def _state_file(tmp_path):
    return str(tmp_path / "state.json")


def _fake_ok_response():
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps({"category": "Прочее"}).encode()
    resp.__enter__.return_value = resp
    return resp


def test_ok_holatda_xabar_yuborilmaydi(tmp_path, monkeypatch):
    monkeypatch.setattr(check_proxy, "STATE_PATH", _state_file(tmp_path))
    monkeypatch.setattr(check_proxy, "TELEGRAM_TOKEN", "t")
    monkeypatch.setattr(check_proxy, "TELEGRAM_CHAT_ID", "1")

    with patch("monitor.check_proxy.urllib.request.urlopen", return_value=_fake_ok_response()) as urlopen, \
         patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_not_called()
    state = json.loads(open(check_proxy.STATE_PATH).read())
    assert state["status"] == "ok"


def test_birinchi_xato_darhol_xabar_beradi(tmp_path, monkeypatch):
    monkeypatch.setattr(check_proxy, "STATE_PATH", _state_file(tmp_path))

    with patch(
        "monitor.check_proxy.urllib.request.urlopen",
        side_effect=check_proxy.urllib.error.URLError("connection refused"),
    ), patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_called_once()
    assert "XATO" in send.call_args[0][0]
    state = json.loads(open(check_proxy.STATE_PATH).read())
    assert state["status"] == "fail"


def test_ketmaket_xato_3_soatgacha_qayta_xabar_bermaydi(tmp_path, monkeypatch):
    state_path = _state_file(tmp_path)
    monkeypatch.setattr(check_proxy, "STATE_PATH", state_path)
    with open(state_path, "w") as f:
        json.dump({"status": "fail", "last_alert_at": check_proxy.time.time() - 60}, f)

    with patch(
        "monitor.check_proxy.urllib.request.urlopen",
        side_effect=check_proxy.urllib.error.URLError("connection refused"),
    ), patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_not_called()


def test_ketmaket_xato_3_soatdan_keyin_qayta_eslatadi(tmp_path, monkeypatch):
    state_path = _state_file(tmp_path)
    monkeypatch.setattr(check_proxy, "STATE_PATH", state_path)
    monkeypatch.setattr(check_proxy, "ALERT_INTERVAL_SEC", 3 * 3600)
    with open(state_path, "w") as f:
        json.dump({"status": "fail", "last_alert_at": check_proxy.time.time() - 4 * 3600}, f)

    with patch(
        "monitor.check_proxy.urllib.request.urlopen",
        side_effect=check_proxy.urllib.error.URLError("connection refused"),
    ), patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_called_once()
    assert "XATO" in send.call_args[0][0]


def test_tuzalganda_bitta_tuzaldi_xabari(tmp_path, monkeypatch):
    state_path = _state_file(tmp_path)
    monkeypatch.setattr(check_proxy, "STATE_PATH", state_path)
    with open(state_path, "w") as f:
        json.dump({"status": "fail", "last_alert_at": check_proxy.time.time()}, f)

    with patch("monitor.check_proxy.urllib.request.urlopen", return_value=_fake_ok_response()), \
         patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_called_once()
    assert "TUZALDI" in send.call_args[0][0]
    state = json.loads(open(state_path).read())
    assert state["status"] == "ok"


def test_http_xato_kodi_xato_deb_hisoblanadi(tmp_path, monkeypatch):
    monkeypatch.setattr(check_proxy, "STATE_PATH", _state_file(tmp_path))
    http_error = check_proxy.urllib.error.HTTPError(
        "http://x", 502, "Bad Gateway", hdrs=None, fp=None
    )
    http_error.read = lambda: b"proxy xatosi"

    with patch("monitor.check_proxy.urllib.request.urlopen", side_effect=http_error), \
         patch.object(check_proxy, "send_telegram") as send:
        check_proxy.main()

    send.assert_called_once()
    assert "502" in send.call_args[0][0]


class TestProxyApiKeyHeader:
    """Jonli xato (mijoz, 2026-09-25) — §48 #8 bilan `/classify` API-kalit
    talab qila boshlagach, bu skript kalitsiz so'rov yuborib 401 olardi."""

    def test_kalit_sozlangan_bolsa_headerga_qoyiladi(self, monkeypatch):
        monkeypatch.setattr(check_proxy, "PROXY_API_KEY", "sekret-123")
        with patch(
            "monitor.check_proxy.urllib.request.urlopen", return_value=_fake_ok_response()
        ) as urlopen:
            check_proxy.check_proxy()

        req = urlopen.call_args[0][0]
        assert req.headers.get("X-kpgen-api-key") == "sekret-123"

    def test_kalit_sozlanmaganda_header_yoq(self, monkeypatch):
        """Regressiya-qulf — kalit sozlanmagan (production'gacha bo'lgan
        eski) holatda avvalgidek header'siz so'rov yuboriladi."""
        monkeypatch.setattr(check_proxy, "PROXY_API_KEY", None)
        with patch(
            "monitor.check_proxy.urllib.request.urlopen", return_value=_fake_ok_response()
        ) as urlopen:
            check_proxy.check_proxy()

        req = urlopen.call_args[0][0]
        assert "X-kpgen-api-key" not in req.headers
