"""`monitor/check_proxy.py` — holat/throttling mantig'i, sintetik so'rovlar,
qayta urinish va sirlarni yashirish. HAQIQIY tarmoqqa, Anthropic'ga yoki
Telegramga CHIQILMAYDI: `urlopen` har testda mock, sirlar tozalanadi."""

import base64
import json
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from monitor import check_proxy

URLOPEN = "monitor.check_proxy.urllib.request.urlopen"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _izolyatsiya(tmp_path, monkeypatch):
    """Hech qachon haqiqiy tarmoq/sir: urlopen default'da yiqiladi, sirlar yo'q,
    holat — tmp, kutish — 0."""
    monkeypatch.setattr(check_proxy, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(check_proxy, "TELEGRAM_TOKEN", None)
    monkeypatch.setattr(check_proxy, "TELEGRAM_CHAT_ID", None)
    monkeypatch.setattr(check_proxy, "PROXY_API_KEY", None)
    monkeypatch.setattr(check_proxy, "BASE_URL", "http://proxy.test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(check_proxy.time, "sleep", lambda s: None)

    def _taqiqlangan(*a, **k):
        raise AssertionError("haqiqiy tarmoq chaqiruvi taqiqlangan")

    with patch(URLOPEN, side_effect=_taqiqlangan):
        yield


# ------------------------------------------------------------------- yordamchilar

OK_JAVOBLAR = {
    "/classify": {"category": "Прочее"},
    "/vision": {"value": "12", "confidence": "high"},
    "/read_spec": {"sahifa": 1, "bolimlar": [], "otkazib_yuborilgan": []},
}


def _resp(payload, status=200):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


def _http_xato(kod, tana="xato"):
    e = check_proxy.urllib.error.HTTPError("http://x", kod, "err", hdrs=None, fp=None)
    e.read = lambda: tana.encode()
    return e


def _router(javoblar):
    """javoblar: {yo'l: payload | Exception | [ketma-ket natijalar]}; ro'yxatning
    oxirgi elementi takrorlanadi. Yo'l berilmasa — OK_JAVOBLAR."""
    chaqiruvlar = []
    navbat = {k: list(v) for k, v in javoblar.items() if isinstance(v, list)}

    def fn(req, timeout=None):
        yol = req.full_url.replace("http://proxy.test", "")
        chaqiruvlar.append((yol, req))
        v = javoblar.get(yol, OK_JAVOBLAR.get(yol))
        if yol in navbat and isinstance(javoblar[yol], list) and navbat[yol]:
            v = navbat[yol].pop(0) if len(navbat[yol]) > 1 else navbat[yol][0]
        if isinstance(v, Exception):
            raise v
        return _resp(v)

    fn.chaqiruvlar = chaqiruvlar
    return fn


def _holat():
    return json.loads(Path(check_proxy.STATE_PATH).read_text())


def _holat_yoz(data):
    Path(check_proxy.STATE_PATH).write_text(json.dumps(data))


def _yurgiz(argv, javoblar=None):
    r = _router(javoblar or {})
    with patch(URLOPEN, side_effect=r), patch.object(check_proxy, "send_telegram", return_value=True) as send:
        check_proxy.main(argv)
    return r, send


# --------------------------------------------------------------- sintetik rasm

class TestSintetikRasm:
    def test_png_yaroqli_100x100(self):
        Image.open(BytesIO(check_proxy.sintetik_png())).verify()
        rasm = Image.open(BytesIO(check_proxy.sintetik_png()))
        assert rasm.size == (100, 100)
        assert rasm.mode == "L"

    def test_rasmda_matn_bor_va_qutisi_ichida(self):
        rasm = Image.open(BytesIO(check_proxy.sintetik_png()))
        qora = [(x, y) for x in range(100) for y in range(100) if rasm.getpixel((x, y)) == 0]
        assert qora
        x0, y0, x1, y1 = check_proxy._matn_qutisi()
        assert all(x0 <= x < x1 and y0 <= y < y1 for x, y in qora)

    def test_base64_qaytadan_png(self):
        assert base64.b64decode(check_proxy.sintetik_png_base64()) == check_proxy.sintetik_png()


# ----------------------------------------------------------- so'rov shakllari

class TestSorovShakllari:
    def test_vision_sorovi(self):
        r, _ = _yurgiz(["vision"])
        yol, req = r.chaqiruvlar[0]
        tana = json.loads(req.data)
        assert yol == "/vision"
        assert set(tana) == {"image_base64", "context"}
        Image.open(BytesIO(base64.b64decode(tana["image_base64"]))).verify()

    def test_read_spec_sorovi_proxy_sxemasiga_mos(self):
        """So'rov proxy'ning haqiqiy Pydantic sxemasidan o'tishi shart."""
        from app.main import ReadSpecRequest

        r, _ = _yurgiz(["read_spec"])
        yol, req = r.chaqiruvlar[0]
        assert yol == "/read_spec"
        model = ReadSpecRequest.model_validate(json.loads(req.data))
        assert model.sahifa_raqami == 1 and len(model.sozlar) == 1

    def test_vision_sorovi_proxy_sxemasiga_mos(self):
        from app.main import VisionRequest

        r, _ = _yurgiz(["vision"])
        VisionRequest.model_validate(json.loads(r.chaqiruvlar[0][1].data))

    def test_standart_faqat_classify(self):
        r, _ = _yurgiz([])
        assert [y for y, _ in r.chaqiruvlar] == ["/classify"]

    def test_bir_nechta_endpoint_ketma_ket(self):
        r, _ = _yurgiz(["vision", "read_spec"])
        assert [y for y, _ in r.chaqiruvlar] == ["/vision", "/read_spec"]

    def test_noma_lum_endpoint_chiqadi(self):
        with pytest.raises(SystemExit) as e:
            check_proxy.main(["nomalum"])
        assert e.value.code == 64


class TestProxyApiKeyHeader:
    """Jonli xato (mijoz, 2026-09-25) — §48 #8 bilan API-kalit talab
    qilinadi; kalitsiz so'rov 401 olardi."""

    @pytest.mark.parametrize("nom", ["classify", "vision", "read_spec"])
    def test_kalit_sozlangan_bolsa_headerga_qoyiladi(self, monkeypatch, nom):
        monkeypatch.setattr(check_proxy, "PROXY_API_KEY", "sekret-123")
        r, _ = _yurgiz([nom])
        assert r.chaqiruvlar[0][1].headers.get("X-kpgen-api-key") == "sekret-123"

    def test_kalit_sozlanmaganda_header_yoq(self):
        r, _ = _yurgiz(["classify"])
        assert "X-kpgen-api-key" not in r.chaqiruvlar[0][1].headers


# ------------------------------------------------------------ javob tuzilishi

class TestJavobTuzilishi:
    @pytest.mark.parametrize("nom", ["classify", "vision", "read_spec"])
    def test_togri_javob_ok(self, nom):
        with patch(URLOPEN, side_effect=_router({})):
            assert check_proxy.check_endpoint(nom) == ("ok", None)

    @pytest.mark.parametrize(
        "yol,nom,buzuq",
        [
            ("/classify", "classify", {"category": ""}),
            ("/vision", "vision", {"value": "1"}),
            ("/vision", "vision", {"value": "1", "confidence": "???"}),
            ("/read_spec", "read_spec", {"sahifa": 2, "bolimlar": []}),
            ("/read_spec", "read_spec", {"sahifa": 1, "bolimlar": "x"}),
        ],
    )
    def test_buzuq_tuzilma_fail(self, yol, nom, buzuq):
        with patch(URLOPEN, side_effect=_router({yol: buzuq})):
            holat, sabab = check_proxy.check_endpoint(nom)
        assert holat == "fail" and "HTTP 200" in sabab

    def test_royxat_javob_fail(self):
        resp = MagicMock(status=200)
        resp.read.return_value = b'["royxat"]'
        resp.__enter__.return_value = resp
        with patch(URLOPEN, return_value=resp):
            assert check_proxy.check_endpoint("read_spec")[0] == "fail"

    def test_json_emas_fail(self):
        resp = MagicMock(status=200)
        resp.read.return_value = b"<html>"
        resp.__enter__.return_value = resp
        with patch(URLOPEN, return_value=resp):
            assert check_proxy.check_endpoint("vision")[0] == "fail"


# ----------------------------------------------------------- qayta urinish/xabar

class TestQaytaUrinishVaXabar:
    def test_ok_holatda_xabar_yoq_holat_ok(self):
        _, send = _yurgiz(["classify"])
        send.assert_not_called()
        assert _holat()["endpoints"]["classify"]["status"] == "ok"

    def test_birinchi_urinish_yiqilib_ikkinchisi_otsa_xabar_yoq(self):
        r, send = _yurgiz(["vision"], {"/vision": [_http_xato(500), OK_JAVOBLAR["/vision"]]})
        send.assert_not_called()
        assert len(r.chaqiruvlar) == 2
        assert _holat()["endpoints"]["vision"]["status"] == "ok"

    def test_ikkala_urinish_yiqilsa_xabar(self):
        r, send = _yurgiz(["read_spec"], {"/read_spec": _http_xato(502, "Model javobi JSON buzuq")})
        assert len(r.chaqiruvlar) == 2
        send.assert_called_once()
        matn = send.call_args[0][0]
        assert "XATO" in matn and "/read_spec" in matn and "502" in matn and "JSON buzuq" in matn
        assert _holat()["endpoints"]["read_spec"]["status"] == "fail"

    def test_classify_ham_ikki_urinishdan_keyin_xabar_beradi(self):
        r, send = _yurgiz(["classify"], {"/classify": [_http_xato(500), OK_JAVOBLAR["/classify"]]})
        send.assert_not_called()
        r, send = _yurgiz(["classify"], {"/classify": _http_xato(500)})
        assert len(r.chaqiruvlar) == 2
        send.assert_called_once()

    def test_qayta_urinishdan_oldin_60s_kutadi(self, monkeypatch):
        kutish = []
        monkeypatch.setattr(check_proxy.time, "sleep", kutish.append)
        _yurgiz(["classify"], {"/classify": check_proxy.urllib.error.URLError("refused")})
        assert kutish == [60]

    def test_ok_bolsa_kutmaydi(self, monkeypatch):
        kutish = []
        monkeypatch.setattr(check_proxy.time, "sleep", kutish.append)
        _yurgiz(["vision"])
        assert kutish == []

    def test_ulanish_xatosi_xabarda(self):
        _, send = _yurgiz(["classify"], {"/classify": check_proxy.urllib.error.URLError("connection refused")})
        assert "ulanish xatosi" in send.call_args[0][0]

    def test_ketmaket_xato_3_soatgacha_qayta_xabar_bermaydi(self):
        _holat_yoz({"endpoints": {"vision": {"status": "fail", "last_alert_at": check_proxy.time.time() - 60}}, "limit_xabari": {}})
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(500)})
        send.assert_not_called()

    def test_ketmaket_xato_3_soatdan_keyin_qayta_eslatadi(self):
        _holat_yoz({"endpoints": {"vision": {"status": "fail", "last_alert_at": check_proxy.time.time() - 4 * 3600}}, "limit_xabari": {}})
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(500)})
        send.assert_called_once()

    def test_tuzalganda_bitta_tuzaldi_endpoint_nomi_bilan(self):
        _holat_yoz({"endpoints": {"read_spec": {"status": "fail", "last_alert_at": check_proxy.time.time()}}, "limit_xabari": {}})
        _, send = _yurgiz(["read_spec"])
        send.assert_called_once()
        assert "TUZALDI" in send.call_args[0][0] and "/read_spec" in send.call_args[0][0]
        assert _holat()["endpoints"]["read_spec"]["status"] == "ok"

    def test_endpointlar_holati_mustaqil(self):
        _yurgiz(["vision", "read_spec"], {"/vision": _http_xato(500)})
        e = _holat()["endpoints"]
        assert e["vision"]["status"] == "fail" and e["read_spec"]["status"] == "ok"

    def test_telegram_yuborilmasa_last_alert_yangilanmaydi(self):
        r = _router({"/vision": _http_xato(500)})
        with patch(URLOPEN, side_effect=r), patch.object(check_proxy, "send_telegram", return_value=False):
            check_proxy.main(["vision"])
        assert _holat()["endpoints"]["vision"]["last_alert_at"] == 0

    def test_telegram_yuborilmasa_tuzaldi_keyingi_yurishda_qayta_uriniladi(self):
        _holat_yoz({"endpoints": {"vision": {"status": "fail", "last_alert_at": 1}}, "limit_xabari": {}})
        r = _router({})
        with patch(URLOPEN, side_effect=r), patch.object(check_proxy, "send_telegram", return_value=False):
            check_proxy.main(["vision"])
        assert _holat()["endpoints"]["vision"]["status"] == "fail"

    def test_eski_holat_formati_classify_ga_otadi(self):
        _holat_yoz({"status": "fail", "last_alert_at": check_proxy.time.time()})
        _, send = _yurgiz(["classify"])
        assert "TUZALDI" in send.call_args[0][0]


# ------------------------------------------------------------ kunlik limit 429

class TestKunlikLimit:
    LIMIT = _http_xato(429, json.dumps({"error": "AI kunlik xarajat chegarasiga yetildi — ertaga qayta urinib ko'ring"}))

    def test_limit_xato_emas_qayta_urinish_yoq(self):
        r, send = _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        assert len(r.chaqiruvlar) == 1
        assert _holat()["endpoints"]["read_spec"]["status"] == "ok"
        assert "XATO" not in send.call_args[0][0]

    def test_limit_xabari_aniq_matn(self):
        _, send = _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        send.assert_called_once_with("kpgen-proxy: kunlik AI limiti tugadi, /read_spec bugun ishlamaydi")

    def test_limit_xabari_kuniga_bir_marta(self):
        _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        _, send = _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        send.assert_not_called()

    def test_limit_xabari_ertasi_kuni_yana(self):
        _holat_yoz({"endpoints": {}, "limit_xabari": {"read_spec": "2000-01-01"}})
        _, send = _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        send.assert_called_once()

    def test_boshqa_429_xato(self):
        r, send = _yurgiz(["vision"], {"/vision": _http_xato(429, "rate limit")})
        assert len(r.chaqiruvlar) == 2
        assert "XATO" in send.call_args[0][0]

    def test_limit_fail_holatini_tozalamaydi(self):
        """Limit — na ok, na fail: oldingi 'fail' holat o'zgarmaydi."""
        _holat_yoz({"endpoints": {"read_spec": {"status": "fail", "last_alert_at": 5}}, "limit_xabari": {}})
        _yurgiz(["read_spec"], {"/read_spec": self.LIMIT})
        assert _holat()["endpoints"]["read_spec"]["status"] == "fail"


# ---------------------------------------------------------------------- sirlar

class TestSirlar:
    def test_anthropic_kaliti_yashiriladi(self):
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(500, "invalid x-api-key sk-ant-api03-ABCdef_123-xyz")})
        matn = send.call_args[0][0]
        assert "sk-ant" not in matn and "***" in matn

    def test_proxy_kaliti_yashiriladi(self, monkeypatch):
        monkeypatch.setattr(check_proxy, "PROXY_API_KEY", "proxy-sekret-999")
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(401, "kalit proxy-sekret-999 noto'g'ri")})
        assert "proxy-sekret-999" not in send.call_args[0][0]

    def test_bot_token_yashiriladi(self):
        assert "AAHxxxx" not in check_proxy.sirlarni_yashir("url bot123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxx/send")

    def test_xato_matni_qisqartiriladi(self):
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(500, "x" * 5000)})
        assert len(send.call_args[0][0]) < 400

    def test_kalit_qisqartish_chegarasida_ham_yashiriladi(self):
        tana = "a" * 190 + " sk-ant-api03-" + "Z" * 40
        _, send = _yurgiz(["vision"], {"/vision": _http_xato(500, tana)})
        assert "sk-ant" not in send.call_args[0][0] and "ZZZZ" not in send.call_args[0][0]


class TestTelegramYuborish:
    def test_sozlanmagan_false_va_tarmoq_yoq(self):
        assert check_proxy.send_telegram("x") is False  # urlopen taqiqlangan — chaqirilmasligi kerak

    def test_sozlangan_yuboradi(self, monkeypatch):
        monkeypatch.setattr(check_proxy, "TELEGRAM_TOKEN", "tok")
        monkeypatch.setattr(check_proxy, "TELEGRAM_CHAT_ID", "42")
        with patch(URLOPEN, return_value=_resp({})) as u:
            assert check_proxy.send_telegram("salom") is True
        assert "api.telegram.org/bottok/sendMessage" in u.call_args[0][0].full_url

    def test_xato_False_qaytaradi_va_qulamaydi(self, monkeypatch):
        monkeypatch.setattr(check_proxy, "TELEGRAM_TOKEN", "tok")
        monkeypatch.setattr(check_proxy, "TELEGRAM_CHAT_ID", "42")
        with patch(URLOPEN, side_effect=OSError("net")):
            assert check_proxy.send_telegram("salom") is False


# --------------------------------------------------------- install_monitor.sh

def _bash():
    """Faqat haqiqiy POSIX bash (Windows'dagi WSL launcher emas)."""
    yol = shutil.which("bash")
    if not yol:
        return None
    try:
        r = subprocess.run([yol, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return yol if r.returncode == 0 and r.stdout.strip() == "ok" else None


@pytest.mark.skipif(_bash() is None, reason="bash yo'q")
class TestInstallSkript:
    SKRIPT = (ROOT / "deploy" / "install_monitor.sh").as_posix()

    def _env_tekshir(self, tmp_path, matn):
        f = tmp_path / "secrets.env"
        if matn is not None:
            f.write_text(matn, encoding="utf-8")
        env = {**os.environ, "KPGEN_MONITOR_ENV_FILE": f.as_posix()}
        return subprocess.run(
            [_bash(), self.SKRIPT, "--check-env"],
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_sintaksis(self):
        r = subprocess.run([_bash(), "-n", self.SKRIPT], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_kalit_bor_otadi(self, tmp_path):
        r = self._env_tekshir(tmp_path, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=1\nKPGEN_PROXY_API_KEY=abc123\n")
        assert r.returncode == 0, r.stderr
        assert "abc123" not in r.stdout + r.stderr  # qiymat chiqarilmaydi

    def test_kalit_yoq_aniq_xato(self, tmp_path):
        r = self._env_tekshir(tmp_path, "TELEGRAM_BOT_TOKEN=t\nTELEGRAM_CHAT_ID=1\n")
        assert r.returncode == 1 and "KPGEN_PROXY_API_KEY" in r.stderr

    def test_kalit_bosh_xato(self, tmp_path):
        r = self._env_tekshir(tmp_path, 'KPGEN_PROXY_API_KEY=""\n')
        assert r.returncode == 1 and "KPGEN_PROXY_API_KEY" in r.stderr

    def test_fayl_yoq_xato(self, tmp_path):
        r = self._env_tekshir(tmp_path, None)
        assert r.returncode == 1 and "topilmadi" in r.stderr

    def test_telegram_bosh_ogohlantirish_lekin_otadi(self, tmp_path):
        r = self._env_tekshir(tmp_path, "KPGEN_PROXY_API_KEY=abc123\n")
        assert r.returncode == 0 and "OGOHLANTIRISH" in r.stderr


def test_timer_va_service_fayllari_mos():
    """ExecStart haqiqiy skriptga va haqiqiy endpoint nomlariga ishora qiladi."""
    for fayl, nomlar in (
        ("kpgen-proxy-monitor.service", {"classify"}),
        ("kpgen-proxy-monitor-ai.service", {"vision", "read_spec"}),
    ):
        matn = (ROOT / "monitor" / fayl).read_text(encoding="utf-8")
        ex = next(l for l in matn.splitlines() if l.startswith("ExecStart="))
        assert "/opt/kpgen-proxy-monitor/check_proxy.py" in ex
        assert set(ex.split("check_proxy.py")[1].split()) == nomlar
        assert nomlar <= set(check_proxy.ENDPOINTLAR)
    assert "00/4:07" in (ROOT / "monitor" / "kpgen-proxy-monitor-ai.timer").read_text(encoding="utf-8")
