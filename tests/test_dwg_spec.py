"""`/dwg_spec` endpoint testlari — HAQIQIY tarmoqqa chiqmasdan, mock
bilan (Faza-45-topshiriq §B, mijoz, 2026-09-08)."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.anthropic_client import ProxyError
from app.main import app

client = TestClient(app)

_ELEMENTS = [
    {"text": "КЭ1", "x": 100.0, "y": 200.0, "layer": "0"},
    {"text": "Конвектор электрический", "x": 120.0, "y": 200.0, "layer": "0"},
    {"text": "шт", "x": 300.0, "y": 200.0, "layer": "0"},
    {"text": "2", "x": 320.0, "y": 200.0, "layer": "0"},
]


def test_dwg_spec_toza_javob():
    model_javobi = json.dumps({
        "positions": [
            {
                "naim": "Конвектор электрический",
                "ed": "шт",
                "kol": 2,
                "manba_matnlar": ["КЭ1", "Конвектор электрический", "шт", "2"],
            }
        ]
    })
    with patch("app.main.ask_claude_dwg_spec", return_value=model_javobi):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["kol"] == 2
    assert body["positions"][0]["manba_matnlar"] == ["КЭ1", "Конвектор электрический", "шт", "2"]


def test_dwg_spec_bosh_natija():
    with patch("app.main.ask_claude_dwg_spec", return_value='{"positions": []}'):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_dwg_spec_buzuq_json_bosh_royxat_qaytaradi():
    """Model JSON EMAS matn qaytarsa (masalan "Kechirasiz, topa olmadim")
    — server qulamaydi, bo'sh positions qaytaradi (xato emas, chunki
    bu "aniq javob yo'q" holati, tarmoq xatosi emas)."""
    with patch("app.main.ask_claude_dwg_spec", return_value="Kechirasiz, men bu jadvalni topa olmadim."):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_dwg_spec_schema_mos_kelmasa_bosh_royxat():
    """Model to'g'ri JSON, lekin majburiy maydon (`manba_matnlar`) yo'q
    — bu pozitsiya SERVER darajasida ham rad etiladi (ikki qavatli
    himoya — kpgen tomonida ham qaytadan tekshiriladi)."""
    model_javobi = json.dumps({"positions": [{"naim": "X", "ed": "шт", "kol": 5}]})
    with patch("app.main.ask_claude_dwg_spec", return_value=model_javobi):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    assert resp.json()["positions"] == []


def test_dwg_spec_markdown_kod_blokidagi_json_togri_oqiladi():
    """Haqiqiy topilgan xato (Мимар sinovi, 2026-09-08, bug #3): model
    promptdagi "faqat JSON" talabiga qaramay, javobni tabiiy-til izohi
    va ```json ... ``` kod bloki bilan o'radi. Bu ANIQLANGANDA (model
    ICHKI JSON'i to'g'ri edi) endi to'g'ri parse qilinishi shart."""
    model_javobi = (
        "Tahlil natijasida quyidagi pozitsiyalarni topdim.\n\n"
        "```json\n"
        '{"positions": [{"naim": "Конвектор электрический", "ed": "шт", '
        '"kol": 2, "manba_matnlar": ["КЭ1", "Конвектор электрический", "шт", "2"]}]}\n'
        "```"
    )
    with patch("app.main.ask_claude_dwg_spec", return_value=model_javobi):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["naim"] == "Конвектор электрический"


def test_dwg_spec_izohsiz_json_ham_togri_oqiladi():
    """Kod bloki YO'Q, faqat oldida/orqasida erkin matn bo'lsa ham —
    birinchi `{`dan oxirgi `}`gacha bo'lgan qism ajratib olinadi."""
    model_javobi = (
        'Mana natija: {"positions": [{"naim": "X", "ed": "шт", "kol": 1, '
        '"manba_matnlar": ["X", "шт", "1"]}]} — tayyor.'
    )
    with patch("app.main.ask_claude_dwg_spec", return_value=model_javobi):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    assert len(resp.json()["positions"]) == 1


def test_dwg_spec_kol_null_qabul_qilinadi():
    """Model noaniq miqdorni "null" deb ber sa — bu TO'G'RI, taxminiy
    son emas ("??" bo'lib qoladi, kpgen tomonida)."""
    model_javobi = json.dumps({
        "positions": [{"naim": "X", "ed": "шт", "kol": None, "manba_matnlar": ["X", "шт"]}]
    })
    with patch("app.main.ask_claude_dwg_spec", return_value=model_javobi):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})

    assert resp.status_code == 200
    assert resp.json()["positions"][0]["kol"] is None


def test_dwg_spec_anthropic_xato_502():
    with patch(
        "app.main.ask_claude_dwg_spec",
        side_effect=ProxyError("Anthropic API bilan bog'lanib bo'lmadi", status_code=502),
    ):
        resp = client.post("/dwg_spec", json={"elements": _ELEMENTS})
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_dwg_spec_bosh_elementlar_royxati_422():
    resp = client.post("/dwg_spec", json={"elements": []})
    assert resp.status_code == 422


def test_dwg_spec_juda_kop_element_422():
    juda_kop = [{"text": "x", "x": 0.0, "y": 0.0, "layer": "0"} for _ in range(5001)]
    resp = client.post("/dwg_spec", json={"elements": juda_kop})
    assert resp.status_code == 422
