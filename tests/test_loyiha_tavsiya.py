"""A8a — `/loyiha_tavsiya` testlari. Anthropic SDK MOCK (`anthropic.Anthropic`) — haqiqiy so'rov yuborilmaydi.

Model javoblari namunalari kpgen PR #129 testlaridan (`tests/test_loyiha_ai_tavsiya.py::Proxy`, `_jihoz`) AYNAN
ko'chirilgan: proxy ularni o'zgartirmasdan o'tkazishi va kpgen klienti (`kpgen/ai/xona_tavsiya.py`) ularni qabul
qilishi shart. kpgen repo'si yonida bo'lsa (`KPGEN_REPO` yoki `../kpgen`), oxirgi test kpgen klientining O'Z kodini
shu proxy orqali yurgizadi."""

import base64
import importlib.util
import logging
import os
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, kunlik_xarajat
from app.main import app

client = TestClient(app)

XONA_NOMI = "Гар-ная"
VARIANTLAR = [{"kalit": "garderob", "nomi": "гардеробная"}, {"kalit": "garaj", "nomi": "гараж"},
              {"kalit": "kladovaya", "nomi": "кладовая"}]
JIHOZLAR = ["unitaz", "vanna", "dush", "rakovina"]


def _jihoz(**holat) -> dict:
    """kpgen `tests/test_loyiha_ai_tavsiya.py::_jihoz` — AYNAN."""
    d = {j: {"holat": "yoq"} for j in JIHOZLAR}
    for j, v in holat.items():
        d[j] = {"holat": "topildi", "joy": v} if isinstance(v, list) else {"holat": v}
    return d


# kpgen `Proxy` sinfidagi mock javoblar (vazifa va ikki sanuzel)
KPGEN_VAZIFA = {"vazifa": "garderob", "dalil": "Гар-ная"}
KPGEN_JIHOZ_1 = _jihoz(unitaz=[0.5, 0.5], dush="nomalum", rakovina=[0.55, 0.5])
KPGEN_JIHOZ_2 = _jihoz(unitaz=[0.5, 0.5], dush=[0.45, 0.55])


def _png(w=200, h=150) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _xona_sorov(**o):
    d = {"vazifa": "xona_vazifasi", "model": "claude-sonnet-5", "prompt_versiya": "a8a-1", "sxema_versiya": 1,
         "xona_nomi": XONA_NOMI, "variantlar": VARIANTLAR}
    d.update(o)
    return d


def _sanuzel_sorov(rasm: bytes | None = None, **o):
    d = {"vazifa": "sanuzel_jihozlari", "model": "claude-sonnet-5", "prompt_versiya": "a8a-1", "sxema_versiya": 1,
         "xona_nomi": "С/у", "jihozlar": JIHOZLAR, "image_base64": _b64(rasm if rasm is not None else _png())}
    d.update(o)
    return d


class FakeSDK:
    """`anthropic.Anthropic` o'rniga: tool-chaqiruv javobi, `create` argumentlarini yozadi."""

    def __init__(self, tool_input=None, xato=None, usage=(1000, 100)):
        self.tool_input, self.xato, self.usage = tool_input, xato, usage
        self.client_kwargs: dict = {}
        self.create_kwargs: dict = {}

    def __call__(self, **kw):
        self.client_kwargs = kw
        messages = MagicMock()
        messages.create.side_effect = self._create
        return SimpleNamespace(messages=messages)

    def _create(self, **kw):
        self.create_kwargs = kw
        if self.xato:
            raise self.xato
        blok = SimpleNamespace(type="tool_use", name=kw["tools"][0]["name"], input=self.tool_input, id="t1")
        return SimpleNamespace(content=[blok], stop_reason="tool_use",
                               usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]))


@pytest.fixture(autouse=True)
def _muhit(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: None)
    monkeypatch.setattr("app.anthropic_client.get_api_key", lambda: "fake-key")
    kunlik_xarajat._holat.update(sana=None, jami_dollar=0.0)
    yield
    kunlik_xarajat._holat.update(sana=None, jami_dollar=0.0)


def _sdk(monkeypatch, **kw) -> FakeSDK:
    f = FakeSDK(**kw)
    monkeypatch.setattr("app.anthropic_client.anthropic.Anthropic", f)
    return f


# --- muvaffaqiyatli yo'llar (kpgen mock namunalari) ------------------------------------------------------------------

def test_xona_vazifasi_kpgen_namunasi(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    r = client.post("/loyiha_tavsiya", json=_xona_sorov())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["vazifa"] == "garderob" and d["dalil"] == "Гар-ная"
    # narx — mavjud jadval bo'yicha (sonnet-5: $2 / $10 per 1M) va kunlik hisobga qo'shildi
    assert d["narx"] == pytest.approx(1000 / 1e6 * 2 + 100 / 1e6 * 10)
    assert kunlik_xarajat.bugungi_xarajat() == pytest.approx(d["narx"])
    k = sdk.create_kwargs
    assert k["model"] == config.TAVSIYA_MODEL_NAME and "temperature" not in k
    assert k["thinking"] == {"type": "disabled"}
    assert k["tool_choice"] == {"type": "tool", "name": "xona_vazifasi_javob"}
    enum = k["tools"][0]["input_schema"]["properties"]["vazifa"]["enum"]
    assert enum == ["garderob", "garaj", "kladovaya", None]
    assert sdk.client_kwargs["max_retries"] == 0 and sdk.client_kwargs["timeout"] == config.TAVSIYA_TIMEOUT_MATN


def test_xona_vazifasi_null_ne_znayu(monkeypatch):
    _sdk(monkeypatch, tool_input={"vazifa": None, "dalil": ""})
    r = client.post("/loyiha_tavsiya", json=_xona_sorov())
    assert r.status_code == 200 and r.json()["vazifa"] is None and r.json()["dalil"] == ""


def test_klient_modeli_emas_proxy_modeli(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    client.post("/loyiha_tavsiya", json=_xona_sorov(model="claude-opus-qimmat"))
    assert sdk.create_kwargs["model"] == config.TAVSIYA_MODEL_NAME


@pytest.mark.parametrize("namuna", [KPGEN_JIHOZ_1, KPGEN_JIHOZ_2])
def test_sanuzel_jihozlari_kpgen_namunasi(monkeypatch, namuna):
    sdk = _sdk(monkeypatch, tool_input={"jihozlar": namuna})
    r = client.post("/loyiha_tavsiya", json=_sanuzel_sorov())
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d["jihozlar"]) == set(JIHOZLAR) and d["narx"] > 0
    for j, e in namuna.items():
        assert d["jihozlar"][j] == {"holat": e["holat"], "joy": e.get("joy")}
    img = sdk.create_kwargs["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/png"
    assert sdk.create_kwargs["tool_choice"]["name"] == "sanuzel_jihozlari_javob"
    assert sdk.client_kwargs["timeout"] == config.TAVSIYA_TIMEOUT_RASM


# --- variantdan tashqari vazifa: null EMAS, 502 EMAS — kpgen o'zi rad etadi ---------------------------------------

def test_variantdan_tashqari_vazifa_ozgarishsiz(monkeypatch):
    """kpgen test_nom_ozgarsa_eskirgan_va_rad: proxy «sauna» qaytaradi → kpgen «не из списка — отклонено»
    ko'rsatadi. null bo'lsa xato yashirinardi; 502 bo'lsa kpgen butun AI oqimini to'xtatardi."""
    _sdk(monkeypatch, tool_input={"vazifa": "sauna", "dalil": "Гар-ная"})
    r = client.post("/loyiha_tavsiya", json=_xona_sorov())
    assert r.status_code == 200 and r.json()["vazifa"] == "sauna"


# --- sxemaga mos bo'lmagan model javobi → 502 (narx baribir hisobga kiradi) --------------------------------------

@pytest.mark.parametrize("vazifa, xom", [
    ("xona", {"vazifa": "garderob"}),                                        # dalil yo'q
    ("xona", {"vazifa": 5, "dalil": "x"}),
    ("xona", {"vazifa": "garderob", "dalil": "x", "ishonch": 0.9}),         # ortiqcha maydon
    ("xona", "garderob"),
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "unitaz": {"holat": "найдено", "joy": [0.5, 0.5]}}}),
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "unitaz": {"holat": "topildi"}}}),          # joysiz topildi
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "unitaz": {"holat": "topildi", "joy": [0.1, 0.2, 0.3, 0.4]}}}),
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "unitaz": {"holat": "topildi", "joy": [1.5, 0.2]}}}),
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "vanna": {"holat": "yoq", "joy": [0.1, 0.2]}}}),
    ("sanuzel", {"jihozlar": {k: v for k, v in KPGEN_JIHOZ_2.items() if k != "rakovina"}}),  # jihoz tushib qolgan
    ("sanuzel", {"jihozlar": {**KPGEN_JIHOZ_2, "bide": {"holat": "yoq"}}}),
    ("sanuzel", {"jihozlar": KPGEN_JIHOZ_2, "ishonch": 0.9}),
])
def test_sxemaga_mos_emas_502(monkeypatch, vazifa, xom):
    _sdk(monkeypatch, tool_input=xom)
    sorov = _xona_sorov() if vazifa == "xona" else _sanuzel_sorov()
    r = client.post("/loyiha_tavsiya", json=sorov)
    assert r.status_code == 502, r.text
    assert "схеме" in r.json()["error"]
    assert kunlik_xarajat.bugungi_xarajat() > 0


def test_tool_chaqiruvsiz_javob_502(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input={})
    sdk._create = lambda **kw: SimpleNamespace(content=[SimpleNamespace(type="text", text='{"vazifa": null}')],
                                               stop_reason="end_turn",
                                               usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    r = client.post("/loyiha_tavsiya", json=_xona_sorov())
    assert r.status_code == 502


# --- kirish xatolari -------------------------------------------------------------------------------------------------

def test_nomalum_vazifa_400(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input={})
    r = client.post("/loyiha_tavsiya", json=_xona_sorov(vazifa="xona_turi"))
    assert r.status_code == 400 and sdk.create_kwargs == {}


def test_sxema_versiyasi_boshqa_400(monkeypatch):
    _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    assert client.post("/loyiha_tavsiya", json=_xona_sorov(sxema_versiya=2)).status_code == 400


def test_variantlarsiz_va_rasmsiz_422(monkeypatch):
    _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    assert client.post("/loyiha_tavsiya", json=_xona_sorov(variantlar=[])).status_code == 422
    assert client.post("/loyiha_tavsiya", json=_sanuzel_sorov(image_base64=None)).status_code == 422
    assert client.post("/loyiha_tavsiya", json=_sanuzel_sorov(image_base64="bu-rasm-emas")).status_code == 422
    assert client.post("/loyiha_tavsiya", json=_sanuzel_sorov(jihozlar=["bide"])).status_code == 422


@pytest.mark.parametrize("rasm", ["katta_bayt", "katta_tomon"])
def test_katta_rasm_413(monkeypatch, rasm):
    sdk = _sdk(monkeypatch, tool_input={"jihozlar": KPGEN_JIHOZ_2})
    if rasm == "katta_bayt":
        monkeypatch.setattr(config, "TAVSIYA_MAX_RASM_BAYT", 1000)
        png = Image.effect_noise((300, 300), 100).convert("RGB")
        buf = BytesIO()
        png.save(buf, format="PNG")
        b = buf.getvalue()
        assert len(b) > 1000
    else:
        b = _png(config.TAVSIYA_MAX_RASM_TOMON + 1, 50)
    r = client.post("/loyiha_tavsiya", json=_sanuzel_sorov(b))
    assert r.status_code == 413 and sdk.create_kwargs == {}


def test_juda_uzun_base64_dekodlanmasdan_413(monkeypatch):
    monkeypatch.setattr(config, "TAVSIYA_MAX_RASM_BAYT", 1000)
    _sdk(monkeypatch, tool_input={})
    r = client.post("/loyiha_tavsiya", json=_sanuzel_sorov(image_base64="A" * 5000))
    assert r.status_code == 413


# --- auth, kunlik limit, Anthropic xatolari --------------------------------------------------------------------------

def test_auth_kalitsiz_401(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret")
    assert client.post("/loyiha_tavsiya", json=_xona_sorov()).status_code == 401
    assert client.post("/loyiha_tavsiya", json=_xona_sorov(),
                       headers={"X-KPGen-Api-Key": "notogri"}).status_code == 401
    assert sdk.create_kwargs == {}
    r = client.post("/loyiha_tavsiya", json=_xona_sorov(), headers={"X-KPGen-Api-Key": "sekret"})
    assert r.status_code == 200


def test_kunlik_limit_429_sorov_yuborilmaydi(monkeypatch):
    sdk = _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    kunlik_xarajat.qoshish({"model": "claude-sonnet-5", "input_tokens": 10_000_000, "output_tokens": 0})
    for sorov in (_xona_sorov(), _sanuzel_sorov()):
        r = client.post("/loyiha_tavsiya", json=sorov)
        assert r.status_code == 429 and "kunlik xarajat" in r.json()["error"]
    assert sdk.create_kwargs == {}


def test_timeout_504(monkeypatch):
    _sdk(monkeypatch, xato=anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")))
    r = client.post("/loyiha_tavsiya", json=_xona_sorov())
    assert r.status_code == 504


def test_anthropic_rate_limit_429(monkeypatch):
    req = httpx.Request("POST", "https://x")
    _sdk(monkeypatch, xato=anthropic.RateLimitError("rl", response=httpx.Response(429, request=req), body=None))
    assert client.post("/loyiha_tavsiya", json=_xona_sorov()).status_code == 429


# --- maxfiylik: logda rasm va xona nomi yo'q ---------------------------------------------------------------------

def test_logda_rasm_va_matn_yoq(monkeypatch, caplog):
    rasm = _png()
    b64 = _b64(rasm)
    _sdk(monkeypatch, tool_input={"jihozlar": KPGEN_JIHOZ_1})
    with caplog.at_level(logging.DEBUG):
        r1 = client.post("/loyiha_tavsiya", json=_sanuzel_sorov(rasm, xona_nomi="Санузел Иванова"))
        _sdk(monkeypatch, tool_input={"vazifa": "sauna", "dalil": "Гар-ная"})
        r2 = client.post("/loyiha_tavsiya", json=_xona_sorov(xona_nomi="Гар-ная Петрова"))
        _sdk(monkeypatch, tool_input={"vazifa": "garderob", "dalil": "Секрет", "x": 1})
        r3 = client.post("/loyiha_tavsiya", json=_xona_sorov(xona_nomi="Гар-ная Петрова"))
    assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 502)
    assert "Секрет" not in r3.text                       # 502 matnida model javobi ham yo'q
    log = "\n".join(rec.getMessage() for rec in caplog.records)
    for maxfiy in (b64[:40], b64[-40:], "Иванова", "Петрова", "Санузел", "Гар-ная", "Секрет", "гардероб"):
        assert maxfiy not in log, maxfiy
    tavsiya = [rec.getMessage() for rec in caplog.records if rec.getMessage().startswith("loyiha_tavsiya: vazifa=")]
    assert len(tavsiya) == 3
    assert f"hajm={len(rasm)}" in tavsiya[0] and "holat=200" in tavsiya[0] and "narx=$" in tavsiya[0]
    assert "davomiylik=" in tavsiya[0] and "holat=502" in tavsiya[2]


# --- kpgen klientining O'Z kodi shu proxy orqali (repo yonida bo'lsa) ------------------------------------------------

def _kpgen_modul():
    for yol in (os.environ.get("KPGEN_REPO"), Path(__file__).resolve().parents[2] / "kpgen"):
        if yol and (Path(yol) / "kpgen" / "ai" / "xona_tavsiya.py").is_file():
            return Path(yol)
    return None


@pytest.mark.skipif(_kpgen_modul() is None or importlib.util.find_spec("requests") is None,
                    reason="kpgen repo'si (A8a, PR #129) yoki requests yo'q")
def test_kpgen_klienti_bilan_kontrakt(monkeypatch):
    repo = _kpgen_modul()
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "kpgen" or m.startswith("kpgen.")]:
        monkeypatch.delitem(sys.modules, m)
    from kpgen.ai import xona_tavsiya as xt

    class _R:
        def __init__(self, r):
            self.status_code, self._r = r.status_code, r

        def json(self):
            return self._r.json()

    def post(url, json=None, timeout=None, headers=None):
        assert url == "http://proxy.test" + xt.ENDPOINT
        return _R(client.post(xt.ENDPOINT, json=json, headers=headers or {}))

    monkeypatch.setattr(xt.requests, "post", post)
    variantlar = [(v["kalit"], v["nomi"]) for v in VARIANTLAR]

    _sdk(monkeypatch, tool_input=KPGEN_VAZIFA)
    j = xt.vazifa_sora("http://proxy.test", XONA_NOMI, variantlar)
    assert xt.vazifa_tekshir(j, XONA_NOMI, variantlar) == ("garderob", None) and j["narx"] > 0

    _sdk(monkeypatch, tool_input={"vazifa": "sauna", "dalil": "Гар-ная"})
    j = xt.vazifa_sora("http://proxy.test", XONA_NOMI, variantlar)
    assert "не из списка" in xt.vazifa_tekshir(j, XONA_NOMI, variantlar)[1]

    _sdk(monkeypatch, tool_input={"jihozlar": KPGEN_JIHOZ_2})
    j = xt.jihoz_sora("http://proxy.test", _png(), "С/у")
    assert j["jihozlar"]["unitaz"] == {"holat": "topildi", "joy": [0.5, 0.5]}
    assert xt.sanuzel_turi(j["jihozlar"]) == "birlashgan" and j["narx"] > 0

    _sdk(monkeypatch, tool_input={"jihozlar": KPGEN_JIHOZ_1})
    j = xt.jihoz_sora("http://proxy.test", _png(), "С/у")
    assert j["jihozlar"]["dush"]["holat"] == "nomalum" and xt.sanuzel_turi(j["jihozlar"]) is None

    kunlik_xarajat.qoshish({"model": "claude-sonnet-5", "input_tokens": 10_000_000, "output_tokens": 0})
    with pytest.raises(xt.TavsiyaXato) as e:
        xt.vazifa_sora("http://proxy.test", XONA_NOMI, variantlar)
    assert e.value.sabab == xt.LIMIT
