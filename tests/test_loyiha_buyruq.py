"""`/loyiha_buyruq` testlari. Anthropic SDK MOCK — haqiqiy so'rov yuborilmaydi. Model javobi namunasi — kpgen
`tests/test_loyiha_buyruq.py` dagi mock javob shakli (sinov qiymatlari)."""

import pytest
from fastapi.testclient import TestClient

from app import kunlik_xarajat
from app.main import app
from tests.test_loyiha_tavsiya import FakeSDK

client = TestClient(app)

SOROV = {"vazifa": "loyiha_buyruq", "model": "claude-sonnet-5", "prompt_versiya": "buyruq-1",
         "matn": "во второй спальне 2 человека, первую не подключать к рекуператору",
         "xonalar": [{"id": "1.5", "nomi": "Спальня", "qavat": "1 этаж"}, {"id": "1.6", "nomi": "Спальня", "qavat": "1 этаж"}],
         "maydonlar": {"odam": {"tur": "son", "oraliq": [0, 10000], "nomi": "число людей"},
                       "rek": {"tur": "tanlov", "qiymatlar": ["yoq"], "nomi": "рекуператор"},
                       "chiqar": {"tur": "ha", "nomi": "исключить"}}}
JAVOB = {"ozgarishlar": [{"xona": "1.5", "maydon": "rek", "qiymat": "yoq", "dalil": "первую не подключать"},
                         {"xona": "1.6", "maydon": "odam", "qiymat": 2, "dalil": "2 человека"}],
         "tushunilmadi": []}


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


def test_javob_otadi_va_tool_sxemasi(monkeypatch):
    f = _sdk(monkeypatch, tool_input=JAVOB)
    r = client.post("/loyiha_buyruq", json=SOROV)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ozgarishlar"][1] == {"xona": "1.6", "maydon": "odam", "qiymat": 2, "dalil": "2 человека"}
    assert d["narx"] > 0
    t = f.create_kwargs["tools"][0]
    assert t["input_schema"]["properties"]["ozgarishlar"]["items"]["properties"]["xona"]["enum"] == ["1.5", "1.6"]
    assert f.create_kwargs["tool_choice"] == {"type": "tool", "name": t["name"]}


def test_sxemaga_mos_emas_502(monkeypatch):
    _sdk(monkeypatch, tool_input={"ozgarishlar": [{"xona": "1.5"}], "tushunilmadi": []})
    assert client.post("/loyiha_buyruq", json=SOROV).status_code == 502


def test_noto_g_ri_vazifa_va_takror_id(monkeypatch):
    _sdk(monkeypatch, tool_input=JAVOB)
    assert client.post("/loyiha_buyruq", json=dict(SOROV, vazifa="x")).status_code == 400
    x = dict(SOROV, xonalar=[SOROV["xonalar"][0], SOROV["xonalar"][0]])
    assert client.post("/loyiha_buyruq", json=x).status_code == 422


def test_kunlik_chegara_429(monkeypatch):
    f = _sdk(monkeypatch, tool_input=JAVOB)
    monkeypatch.setattr("app.loyiha_buyruq.kunlik_xarajat.chegaraga_yetdimi", lambda: True)
    assert client.post("/loyiha_buyruq", json=SOROV).status_code == 429
    assert f.create_kwargs == {}


def test_matn_logga_yozilmaydi(monkeypatch, caplog):
    _sdk(monkeypatch, tool_input=JAVOB)
    with caplog.at_level("INFO", logger="kpgen_proxy"):
        client.post("/loyiha_buyruq", json=SOROV)
    assert "loyiha_buyruq: holat=200" in caplog.text and "спальн" not in caplog.text.lower()


def _kpgen_repo():
    import os
    from pathlib import Path
    for yol in (os.environ.get("KPGEN_REPO"), Path(__file__).resolve().parents[2] / "kpgen"):
        if yol and (Path(yol) / "kpgen" / "ai" / "buyruq.py").is_file():
            return Path(yol)
    return None


@pytest.mark.skipif(_kpgen_repo() is None, reason="kpgen repo'si (matn bilan buyruq) yonida yo'q")
def test_kpgen_klienti_bilan_kontrakt(monkeypatch):
    """kpgen klienti (`kpgen/ai/buyruq.py`) — so'rovni shu proxy orqali yuboradi va javobni o'z tekshiruvidan o'tkazadi."""
    import importlib.util
    import sys
    if importlib.util.find_spec("requests") is None:
        pytest.skip("requests yo'q")
    monkeypatch.syspath_prepend(str(_kpgen_repo()))
    for m in [m for m in sys.modules if m == "kpgen" or m.startswith("kpgen.")]:
        monkeypatch.delitem(sys.modules, m)
    from kpgen.ai import buyruq as kb

    class _R:
        def __init__(self, r):
            self.status_code, self._r = r.status_code, r

        def json(self):
            return self._r.json()

    monkeypatch.setattr(kb.requests, "post", lambda url, json=None, timeout=None, headers=None:
                        _R(client.post(kb.ENDPOINT, json=json, headers=headers or {})))
    _sdk(monkeypatch, tool_input=JAVOB)
    tanlov = {"rek": ("yoq",)}
    d = kb.tahlil("http://proxy.test", SOROV["matn"], SOROV["xonalar"], tanlov)
    qabul, rad = kb.tekshir(d, SOROV["matn"], SOROV["xonalar"], tanlov)
    assert [(o["xona"], o["maydon"], o["qiymat"]) for o in qabul] == [("1.5", "rek", "yoq"), ("1.6", "odam", 2)]
    assert not rad and kb.narx(d) > 0
