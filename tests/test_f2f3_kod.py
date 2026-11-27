"""`/f2f3_kod` testlari. Anthropic SDK MOCK — haqiqiy so'rov yuborilmaydi. Kontrakt — kpgen klienti
(`kpgen/ai/f2f3_kod.py`) bilan; kod/nomlar — sinov qiymatlari."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import kunlik_xarajat
from app.main import app

client = TestClient(app)

UMUMIY = [{"kod": "E20-2-5", "nom": "Установка жироуловителя", "birlik": "шт"},
          {"kod": "E20-3-1", "nom": "Установка раковин", "birlik": "шт"}]
JADVAL = {"vazifa": "f2f3_kod", "bosqich": "jadval", "model": "claude-haiku-4-5", "prompt_versiya": "f2f3kod-1",
          "sxema_versiya": 1, "umumiy_nomzodlar": UMUMIY,
          "qatorlar": [{"id": "37.0", "nom": "Жировуловитель 300х200", "birlik": "шт"},
                       {"id": "38.0", "nom": "Гвозди", "birlik": "кг"}]}
VARIANT = {"vazifa": "f2f3_kod", "bosqich": "variant", "model": "claude-haiku-4-5", "prompt_versiya": "f2f3kod-1",
           "sxema_versiya": 1,
           "qatorlar": [{"id": "37.0", "nom": "Жировуловитель 300х200", "birlik": "шт",
                         "nomzodlar": [{"kod": "E20-2-5-1", "nom": "до 50 кг", "birlik": "шт"},
                                       {"kod": "E20-2-5-2", "nom": "св. 50 кг", "birlik": "шт"}]}]}
JAVOB = {"javoblar": [{"id": "37.0", "kod": "E20-2-5", "sabab": "Жироуловитель — установка по таблице E20-2-5."},
                      {"id": "38.0", "kod": None, "sabab": "Подходящей нормы в списке нет."}]}


class FakeSDK:
    """`anthropic.Anthropic` o'rniga: matn javobi, `create` argumentlarini yozadi."""

    def __init__(self, matn="", usage=(2000, 100, 30000, 0)):
        self.matn, self.usage = matn, usage
        self.client_kwargs: dict = {}
        self.create_kwargs: dict = {}
        self.chaqiruv = 0

    def __call__(self, **kw):
        self.client_kwargs = kw
        messages = MagicMock()
        messages.create.side_effect = self._create
        return SimpleNamespace(messages=messages)

    def _create(self, **kw):
        self.create_kwargs = kw
        self.chaqiruv += 1
        i, o, oqish, yozish = self.usage
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.matn)], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=i, output_tokens=o,
                                  cache_read_input_tokens=oqish, cache_creation_input_tokens=yozish))


@pytest.fixture(autouse=True)
def _muhit(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: None)
    monkeypatch.setattr("app.anthropic_client.get_api_key", lambda: "fake-key")
    kunlik_xarajat._holat.update(sana=None, jami_dollar=0.0)
    yield
    kunlik_xarajat._holat.update(sana=None, jami_dollar=0.0)


def _sdk(monkeypatch, javob=JAVOB, **kw) -> FakeSDK:
    f = FakeSDK(matn=javob if isinstance(javob, str) else json.dumps(javob, ensure_ascii=False), **kw)
    monkeypatch.setattr("app.anthropic_client.anthropic.Anthropic", f)
    return f


# (1) jadval bosqichi: cache_control birinchi blokda
def test_jadval_bosqichi_cache_control_birinchi_blokda(monkeypatch):
    f = _sdk(monkeypatch)
    r = client.post("/f2f3_kod", json=JADVAL)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["javoblar"] == JAVOB["javoblar"]
    kw = f.create_kwargs
    assert kw["model"] == "claude-haiku-4-5" and kw["max_tokens"] == 4096
    assert "temperature" not in kw                       # SDK qabul qilmaydi — production oldin qulagan
    assert "сметчик" in kw["system"]
    blok1, blok2 = kw["messages"][0]["content"]
    assert blok1["cache_control"] == {"type": "ephemeral"} and "cache_control" not in blok2
    assert "E20-2-5 | Установка жироуловителя | шт" in blok1["text"] and "E20-3-1" in blok1["text"]
    assert "Жировуловитель 300х200" in blok2["text"] and "E20-2-5" not in blok2["text"]
    # narx: input 2000 * 1.00 + output 100 * 5.00 + cache_read 30000 * 0.10 (haiku, $/1M)
    assert d["narx"] == pytest.approx(0.002 + 0.0005 + 0.003)
    assert kunlik_xarajat.bugungi_xarajat() == pytest.approx(d["narx"])      # umumiy kunlik byudjetga kirdi


# (2) variant bosqichi: umumiy ro'yxat YO'Q, nomzodlar qatorning o'zida, kesh belgisi yo'q
def test_variant_bosqichi(monkeypatch):
    f = _sdk(monkeypatch, javob={"javoblar": [{"id": "37.0", "kod": "E20-2-5-2", "sabab": "Вес более 50 кг."}]})
    r = client.post("/f2f3_kod", json=VARIANT)
    assert r.status_code == 200, r.text
    assert r.json()["javoblar"] == [{"id": "37.0", "kod": "E20-2-5-2", "sabab": "Вес более 50 кг."}]
    bloklar = f.create_kwargs["messages"][0]["content"]
    assert len(bloklar) == 1 and "cache_control" not in bloklar[0]
    assert "E20-2-5-1" in bloklar[0]["text"] and "E20-2-5-2" in bloklar[0]["text"]


# (3) noto'g'ri JSON → 502
def test_notogri_json_502(monkeypatch):
    _sdk(monkeypatch, javob="это не JSON {{{")
    r = client.post("/f2f3_kod", json=JADVAL)
    assert r.status_code == 502
    assert "error" in r.json()


def test_javobda_javoblar_royxati_yoq_502(monkeypatch):
    _sdk(monkeypatch, javob={"boshqa": 1})
    assert client.post("/f2f3_kod", json=JADVAL).status_code == 502


def test_json_kod_bloki_bilan_ham_otadi_va_notogri_element_tashlanadi(monkeypatch):
    toza = {"javoblar": [
        {"id": "37.0", "kod": "E20-2-5", "sabab": "ok"},
        {"id": "999", "kod": "E20-2-5", "sabab": "so'rovda bunday id yo'q"},
        {"id": "38.0", "kod": 5, "sabab": "kod son — noto'g'ri"},
        {"id": "38.0", "kod": None, "sabab": "x" * 241},          # sabab > 240 — tashlanadi
        {"id": "38.0", "kod": None, "sabab": None},              # sabab satr emas
        "axlat",
        {"id": "38.0", "kod": None, "sabab": "нормы нет"},
        {"id": "38.0", "kod": "E20-3-1", "sabab": "takror id — birinchisi qoladi"}]}
    _sdk(monkeypatch, javob="```json\n" + json.dumps(toza, ensure_ascii=False) + "\n```")
    r = client.post("/f2f3_kod", json=JADVAL)
    assert r.status_code == 200, r.text
    assert r.json()["javoblar"] == [{"id": "37.0", "kod": "E20-2-5", "sabab": "ok"},
                                    {"id": "38.0", "kod": None, "sabab": "нормы нет"}]


# (4) > 25 qator → 400 (Anthropic chaqirilmaydi)
def test_25_dan_ortiq_qator_400(monkeypatch):
    f = _sdk(monkeypatch)
    ok = dict(JADVAL, qatorlar=[{"id": str(i), "nom": "x", "birlik": "шт"} for i in range(25)])
    assert client.post("/f2f3_kod", json=ok).status_code == 200
    f.chaqiruv = 0
    kop = dict(JADVAL, qatorlar=[{"id": str(i), "nom": "x", "birlik": "шт"} for i in range(26)])
    assert client.post("/f2f3_kod", json=kop).status_code == 400
    assert f.chaqiruv == 0


# (5) ruxsatsiz model → 400
def test_ruxsatsiz_model_400(monkeypatch):
    f = _sdk(monkeypatch)
    assert client.post("/f2f3_kod", json=dict(JADVAL, model="claude-opus-9")).status_code == 400
    assert f.chaqiruv == 0
    # model berilmasa — sukut (haiku)
    yoq = {k: v for k, v in JADVAL.items() if k != "model"}
    assert client.post("/f2f3_kod", json=yoq).status_code == 200
    assert f.create_kwargs["model"] == "claude-haiku-4-5"


# (6) kalitsiz → 401
def test_kalitsiz_401(monkeypatch):
    f = _sdk(monkeypatch)
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")
    assert client.post("/f2f3_kod", json=JADVAL).status_code == 401
    assert client.post("/f2f3_kod", json=JADVAL, headers={"X-KPGen-Api-Key": "notogri"}).status_code == 401
    assert f.chaqiruv == 0
    assert client.post("/f2f3_kod", json=JADVAL, headers={"X-KPGen-Api-Key": "sekret-kalit"}).status_code == 200


# (7) kunlik limit → 429 (Anthropic'ga so'rov YUBORILMAYDI)
def test_kunlik_chegara_429(monkeypatch):
    f = _sdk(monkeypatch)
    monkeypatch.setattr("app.f2f3_kod.kunlik_xarajat.chegaraga_yetdimi", lambda: True)
    r = client.post("/f2f3_kod", json=JADVAL)
    assert r.status_code == 429
    assert "kunlik xarajat" in r.json()["error"]
    assert f.chaqiruv == 0


def test_haqiqiy_chegara_oshganda_429(monkeypatch):
    """Mock'siz chegara: avvalgi so'rovlar jamini chegaradan oshirsa, keyingisi 429."""
    f = _sdk(monkeypatch)
    kunlik_xarajat.qoshish({"model": "claude-sonnet-5", "input_tokens": 3_000_000, "output_tokens": 0})   # $6 > $5
    assert client.post("/f2f3_kod", json=VARIANT).status_code == 429
    assert f.chaqiruv == 0


def test_boshqa_sorov_xatolari(monkeypatch):
    f = _sdk(monkeypatch)
    assert client.post("/f2f3_kod", json=dict(JADVAL, vazifa="x")).status_code == 400
    assert client.post("/f2f3_kod", json=dict(JADVAL, umumiy_nomzodlar=[])).status_code == 400
    bosh = dict(VARIANT, qatorlar=[dict(VARIANT["qatorlar"][0], nomzodlar=[])])
    assert client.post("/f2f3_kod", json=bosh).status_code == 400
    takror = dict(JADVAL, qatorlar=[JADVAL["qatorlar"][0], JADVAL["qatorlar"][0]])
    assert client.post("/f2f3_kod", json=takror).status_code == 422
    assert client.post("/f2f3_kod", json=dict(JADVAL, bosqich="x")).status_code == 422
    assert f.chaqiruv == 0


def test_anthropic_xatosi_status_bilan_qaytadi(monkeypatch):
    import anthropic

    class _Xato(FakeSDK):
        def _create(self, **kw):
            raise anthropic.APITimeoutError(request=MagicMock())

    monkeypatch.setattr("app.anthropic_client.anthropic.Anthropic", _Xato())
    assert client.post("/f2f3_kod", json=JADVAL).status_code == 504


def test_nomlar_logga_yozilmaydi(monkeypatch, caplog):
    _sdk(monkeypatch)
    with caplog.at_level("INFO", logger="kpgen_proxy"):
        client.post("/f2f3_kod", json=JADVAL)
    assert "f2f3_kod: holat=200 bosqich=jadval" in caplog.text
    assert "жиро" not in caplog.text.lower() and "E20-2-5" not in caplog.text


def _kpgen_repo():
    for yol in (os.environ.get("KPGEN_REPO"), Path(__file__).resolve().parents[2] / "kpgen"):
        if yol and (Path(yol) / "kpgen" / "ai" / "f2f3_kod.py").is_file():
            return Path(yol)
    return None


@pytest.mark.skipif(_kpgen_repo() is None, reason="kpgen repo'si (kpgen/ai/f2f3_kod.py) yonida yo'q — KPGEN_REPO")
def test_kpgen_klienti_bilan_kontrakt(monkeypatch):
    """kpgen klienti (`kpgen/ai/f2f3_kod.py::sora`) so'rovni shu proxy orqali yuboradi, javobni o'z tekshiruvidan o'tkazadi."""
    import importlib.util
    import sys
    if importlib.util.find_spec("requests") is None:
        pytest.skip("requests yo'q")
    monkeypatch.syspath_prepend(str(_kpgen_repo()))
    for m in [m for m in sys.modules if m == "kpgen" or m.startswith("kpgen.")]:
        monkeypatch.delitem(sys.modules, m)
    from kpgen.ai import f2f3_kod as fk

    class _R:
        def __init__(self, r):
            self.status_code, self._r = r.status_code, r

        def json(self):
            return self._r.json()

    monkeypatch.setattr(fk.requests, "post", lambda url, json=None, timeout=None, headers=None:
                        _R(client.post(fk.ENDPOINT, json=json, headers=headers or {})))
    N = lambda kod, nom, birlik: SimpleNamespace(kod=kod, nom=nom, birlik=birlik)   # noqa: E731
    f = _sdk(monkeypatch)
    qatorlar = [{"id": "37.0", "nom": "Жировуловитель 300х200", "birlik": "шт"}, {"id": "38.0", "nom": "Гвозди", "birlik": "кг"}]
    d = fk.sora("http://proxy.test", fk.JADVAL, qatorlar, umumiy=[N(**u) for u in UMUMIY])
    assert d["javoblar"]["37.0"]["kod"] == "E20-2-5" and d["javoblar"]["38.0"]["kod"] is None and d["narx"] > 0
    assert f.create_kwargs["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    nomzodlar = [N("E20-2-5-1", "до 50 кг", "шт"), N("E20-2-5-2", "св. 50 кг", "шт")]
    _sdk(monkeypatch, javob={"javoblar": [{"id": "37.0", "kod": "E20-2-5-2", "sabab": "Вес более 50 кг."}]})
    d = fk.sora("http://proxy.test", fk.VARIANT, [dict(qatorlar[0], nomzodlar=nomzodlar)])
    assert fk.tekshir(d["javoblar"]["37.0"], nomzodlar)[0] == "E20-2-5-2"
