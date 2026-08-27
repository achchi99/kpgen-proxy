"""`/vision` endpoint testlari — HAQIQIY tarmoqqa chiqmasdan, mock bilan.

`ask_claude_vision` har doim mock qilinadi (`test_vision_kalit_yoq_500`dan
tashqari — u haqiqiy kalit-tekshiruv yo'lini sinaydi, lekin baribir
tarmoqqa chiqmaydi, chunki kalit yo'qligi tarmoq chaqiruvidan OLDIN
aniqlanadi)."""

import base64
import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.anthropic_client import ProxyError
from app.main import app

client = TestClient(app)


def _sample_image_base64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_vision_toza_raqam_high_confidence():
    with patch("app.main.ask_claude_vision", return_value="39"):
        resp = client.post(
            "/vision", json={"image_base64": _sample_image_base64(), "context": "Кол-во, 500x150"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"value": "39", "confidence": "high"}


def test_vision_kasr_raqam_ham_high():
    with patch("app.main.ask_claude_vision", return_value="6.3"):
        resp = client.post("/vision", json={"image_base64": _sample_image_base64(), "context": "test"})
    assert resp.status_code == 200
    assert resp.json() == {"value": "6.3", "confidence": "high"}


def test_vision_null_javob_low_confidence():
    with patch("app.main.ask_claude_vision", return_value="null"):
        resp = client.post("/vision", json={"image_base64": _sample_image_base64(), "context": "test"})
    assert resp.status_code == 200
    assert resp.json() == {"value": None, "confidence": "low"}


def test_vision_raqam_plus_soz_low_confidence():
    """Server O'Z regex qoidasini qo'llaydi — model "39 шт" deb aniq
    yozib bergan bo'lsa ham, bu qat'iy raqam-formatga mos emas."""
    with patch("app.main.ask_claude_vision", return_value="39 шт"):
        resp = client.post("/vision", json={"image_base64": _sample_image_base64(), "context": "test"})
    assert resp.status_code == 200
    assert resp.json() == {"value": None, "confidence": "low"}


def test_vision_buzuq_base64_422():
    resp = client.post("/vision", json={"image_base64": "!!!not-valid-base64!!!", "context": "test"})
    assert resp.status_code == 422


def test_vision_togri_base64_lekin_rasm_emas_422():
    fake = base64.b64encode(b"bu shunchaki matn, rasm emas").decode()
    resp = client.post("/vision", json={"image_base64": fake, "context": "test"})
    assert resp.status_code == 422


def test_vision_kalit_yoq_500(monkeypatch):
    monkeypatch.setattr("app.anthropic_client.get_api_key", lambda: None)
    resp = client.post("/vision", json={"image_base64": _sample_image_base64(), "context": "test"})
    assert resp.status_code == 500
    assert "ANTHROPIC_API_KEY" in resp.json()["error"]


def test_vision_anthropic_xato_502():
    with patch(
        "app.main.ask_claude_vision",
        side_effect=ProxyError("Anthropic API bilan bog'lanib bo'lmadi", status_code=502),
    ):
        resp = client.post("/vision", json={"image_base64": _sample_image_base64(), "context": "test"})
    assert resp.status_code == 502
    assert "error" in resp.json()
