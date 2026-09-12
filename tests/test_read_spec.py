"""`/read_spec` endpoint testlari — HAQIQIY tarmoqqa chiqmasdan, mock
bilan (Faza-72-topshiriq, mijoz, 2026-09-11 — `/dwg_spec` bilan bir
xil naqsh)."""

import base64
import json
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.anthropic_client import ProxyError
from app.main import app

client = TestClient(app)


def _sample_image_base64() -> str:
    buf = BytesIO()
    Image.new("RGB", (20, 20), color="white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


_SOZLAR = [
    {"id": "w0", "matn": "1", "x0": 30.0, "y0": 100.0, "x1": 35.0, "y1": 108.0},
    {"id": "w1", "matn": "Радиатор", "x0": 40.0, "y0": 100.0, "x1": 80.0, "y1": 108.0},
    {"id": "w2", "matn": "10", "x0": 40.0, "y0": 112.0, "x1": 48.0, "y1": 120.0},
    {"id": "w3", "matn": "секций", "x0": 50.0, "y0": 112.0, "x1": 80.0, "y1": 120.0},
    {"id": "w4", "matn": "шт.", "x0": 200.0, "y0": 112.0, "x1": 215.0, "y1": 120.0},
    {"id": "w5", "matn": "1", "x0": 250.0, "y0": 112.0, "x1": 255.0, "y1": 120.0},
]


def _payload(**overrides):
    base = {
        "image_base64": _sample_image_base64(),
        "sozlar": _SOZLAR,
        "sahifa_raqami": 1,
    }
    base.update(overrides)
    return base


def test_read_spec_toza_javob():
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [
            {
                "nom": "Оборудования для отопления",
                "qatorlar": [
                    {
                        "poz": "1",
                        "naim": "Радиатор 10 секций",
                        "ed": "шт.",
                        "kol": "1",
                        "manba": {"naim": ["w1", "w2", "w3"], "ed": "w4", "kol": "w5"},
                        "ishonch": "yuqori",
                    }
                ],
            }
        ],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    body = resp.json()
    assert body["sahifa"] == 1
    assert len(body["bolimlar"]) == 1
    qator = body["bolimlar"][0]["qatorlar"][0]
    assert qator["naim"] == "Радиатор 10 секций"
    assert qator["kol"] == "1"  # XOM MATN, son emas (T1)
    assert qator["manba"] == {"naim": ["w1", "w2", "w3"], "ed": "w4", "kol": "w5"}


def test_read_spec_kol_dual_qiymat_xom_saqlanadi():
    """T1 — model hisoblamaydi: "25/65" kabi dual qiymat SON'ga
    aylantirilmasdan, XOM matn sifatida o'tishi shart."""
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{"nom": "Воздуховоды", "qatorlar": [
            {"naim": "Воздуховод 800x500", "ed": "m/m2", "kol": "25/65"}
        ]}],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["bolimlar"][0]["qatorlar"][0]["kol"] == "25/65"


def test_read_spec_maydon_m2_matn_xom_saqlanadi():
    """Faza-72, 6-bosqich (mijoz, 2026-09-12, sergeli_rp jonli
    tekshiruvi): vozduxovod qatorida ASOSIY "kol" (uzunlik) DAN
    TASHQARI, ALOHIDA "maydon_m2_matn" (masalan "Всего-1,14 кв.м.")
    XOM matn sifatida (hisoblanmasdan) o'tishi shart."""
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{"nom": "Воздуховоды", "qatorlar": [
            {"naim": "Воздуховод 150x150", "ed": "м.", "kol": "1,9",
             "maydon_m2_matn": "Всего-1,14 кв.м."}
        ]}],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    qator = resp.json()["bolimlar"][0]["qatorlar"][0]
    assert qator["kol"] == "1,9"
    assert qator["maydon_m2_matn"] == "Всего-1,14 кв.м."


def test_read_spec_maydon_m2_matn_yoq_bolsa_standart_null():
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{"nom": "X", "qatorlar": [{"naim": "Y", "ed": "шт", "kol": "1"}]}],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["bolimlar"][0]["qatorlar"][0]["maydon_m2_matn"] is None


def test_read_spec_null_maydonlar_qabul_qilinadi():
    """T3 — model noaniq bo'lsa null qo'yadi, taxmin qilmaydi."""
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{"nom": "X", "qatorlar": [
            {"naim": "Noaniq qator", "ed": None, "kol": None, "izoh": "raqam dog' bilan qoplangan"}
        ]}],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    qator = resp.json()["bolimlar"][0]["qatorlar"][0]
    assert qator["ed"] is None
    assert qator["kol"] is None
    assert qator["izoh"] == "raqam dog' bilan qoplangan"


def test_read_spec_otkazib_yuborilgan_royxati():
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [],
        "otkazib_yuborilgan": [{"matn": "Изм. Кол.уч. Лист", "sabab": "shtamp"}],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["otkazib_yuborilgan"] == [{"matn": "Изм. Кол.уч. Лист", "sabab": "shtamp"}]


def test_read_spec_kunlik_xarajat_chegarasida_429_va_anthropicga_sorov_ketmaydi():
    """Faza-72, 4-bosqich (mijoz, 2026-09-12): kunlik chegaraga yetgan
    bo'lsa — Anthropic'ga SO'ROV UMUMAN YUBORILMAYDI (xarajat aynan shu
    yerda to'xtaydi), 429 aniq matn bilan qaytadi."""
    with patch("app.main.kunlik_xarajat.chegaraga_yetdimi", return_value=True):
        with patch("app.main.ask_claude_read_spec") as mock_ask:
            resp = client.post("/read_spec", json=_payload())
            mock_ask.assert_not_called()

    assert resp.status_code == 429
    assert "kunlik" in resp.json()["error"].lower()


def test_read_spec_muvaffaqiyatli_sorov_kunlik_xarajatga_qoshiladi():
    with patch(
        "app.main.ask_claude_read_spec",
        return_value='{"sahifa": 1, "bolimlar": [], "otkazib_yuborilgan": []}',
    ):
        with patch(
            "app.main.anthropic_client.LAST_USAGE",
            {"model": "claude-sonnet-5", "input_tokens": 1000, "output_tokens": 200,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        ):
            with patch("app.main.kunlik_xarajat.qoshish") as mock_qoshish:
                resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    mock_qoshish.assert_called_once()


def test_read_spec_bosh_natija():
    with patch(
        "app.main.ask_claude_read_spec",
        return_value='{"sahifa": 1, "bolimlar": [], "otkazib_yuborilgan": []}',
    ):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["bolimlar"] == []


def test_read_spec_usage_javobga_qoshiladi():
    """Faza-72, Band 1a (mijoz, 2026-09-12): kpgen tomoni (`run_shadow.py
    --max-xarajat`) HAQIQIY xarajatni real vaqtda kuzatishi uchun —
    `anthropic_client.LAST_USAGE` javobga `usage` maydoni sifatida
    qo'shilishi shart."""
    with patch(
        "app.main.ask_claude_read_spec",
        return_value='{"sahifa": 1, "bolimlar": [], "otkazib_yuborilgan": []}',
    ):
        with patch(
            "app.main.anthropic_client.LAST_USAGE",
            {"model": "claude-sonnet-5", "input_tokens": 1000, "output_tokens": 200,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        ):
            resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["usage"] == {
        "model": "claude-sonnet-5", "input_tokens": 1000, "output_tokens": 200,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }


def test_read_spec_buzuq_json_502_xato_qaytaradi():
    """Faza-72, 3-bosqich yakunidan keyingi tuzatish (mijoz, 2026-09-12):
    ILGARI bu holat 200+bo'sh natija bilan "hech narsa topilmadi"
    (haqiqiy, AI tasdiqlagan natija) bilan ARALASHTIRILAR edi — endi
    ANIQ xato (502), xom javob boshi bilan."""
    with patch("app.main.ask_claude_read_spec", return_value="Kechirasiz, o'qiy olmadim."):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 502
    body = resp.json()
    assert "error" in body
    assert "xom_javob_boshi" in body
    assert "Kechirasiz" in body["xom_javob_boshi"]


def test_read_spec_markdown_kod_blokidagi_json_togri_oqiladi():
    model_javobi = (
        "Natija:\n```json\n"
        '{"sahifa": 1, "bolimlar": [{"nom": "X", "qatorlar": '
        '[{"naim": "Y", "ed": "шт", "kol": "1"}]}], "otkazib_yuborilgan": []}\n'
        "```"
    )
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["bolimlar"][0]["qatorlar"][0]["naim"] == "Y"


def test_read_spec_anthropic_xato_502():
    with patch(
        "app.main.ask_claude_read_spec",
        side_effect=ProxyError("Anthropic API bilan bog'lanib bo'lmadi", status_code=502),
    ):
        resp = client.post("/read_spec", json=_payload())
    assert resp.status_code == 502
    assert "error" in resp.json()


def test_read_spec_buzuq_rasm_422():
    resp = client.post("/read_spec", json=_payload(image_base64="!!!not-valid!!!"))
    assert resp.status_code == 422


def test_read_spec_bosh_sozlar_royxati_422():
    resp = client.post("/read_spec", json=_payload(sozlar=[]))
    assert resp.status_code == 422


def test_read_spec_naim_yoq_qator_rad_etiladi():
    """Server-tomon sxema: `naim` majburiy — bo'lmasa butun javob
    ValidationError bilan rad etiladi (502) — ikki qavatli himoya
    (kpgen tomonida ham, T2 mustaqil tekshiruvi orqali)."""
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{"nom": "X", "qatorlar": [{"ed": "шт", "kol": "1"}]}],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 502


def test_read_spec_ishonch_izoh_manba_qator_yoq_bolsa_standart_qiymat():
    """Faza-72, Band 2d (mijoz, 2026-09-12, chiqish-token tejash):
    model endi 'ishonch'/'izoh' maydonlarini ular kerak bo'lmaganda
    BUTUNLAY tushirib qoldiradi (JSON'da kalitning o'zi yo'q) — server
    sxemasi buni standart qiymat bilan qabul qilishi shart, rad
    etmasligi kerak. "manba" ham tushirilsa — bo'sh dict standart."""
    model_javobi = json.dumps({
        "sahifa": 1,
        "bolimlar": [{
            "nom": "X",
            "qatorlar": [{
                "poz": "1", "naim": "Вентилятор", "tip": None, "ed": "шт.",
                "kol": "1", "massa": None, "prim": None,
                # "ishonch", "izoh", "manba" — ATAYLAB yo'q
            }],
        }],
        "otkazib_yuborilgan": [],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    qator = resp.json()["bolimlar"][0]["qatorlar"][0]
    assert qator["ishonch"] == "yuqori"
    assert qator["izoh"] is None
    assert qator["manba"] == {}


def test_read_spec_otkazib_yuborilgan_qisqa_sabab_kodi_qabul_qilinadi():
    """Band 2d: 'sabab' endi qisqa kod ('shtamp', 'eksplikatsiya' va
    h.k.) — erkin uzun matn emas. Server sxemasi bunday qisqa
    stringni oddiy qabul qiladi (qattiq enum-tekshiruv yo'q, model
    formatga rioya qiladi deb kutiladi — tekshiruv T2'da emas)."""
    model_javobi = json.dumps({
        "sahifa": 1, "bolimlar": [],
        "otkazib_yuborilgan": [{"matn": "Лестничная клетка 16.4", "sabab": "eksplikatsiya"}],
    })
    with patch("app.main.ask_claude_read_spec", return_value=model_javobi):
        resp = client.post("/read_spec", json=_payload())

    assert resp.status_code == 200
    assert resp.json()["otkazib_yuborilgan"][0]["sabab"] == "eksplikatsiya"
