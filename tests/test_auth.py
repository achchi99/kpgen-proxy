"""`_require_api_key()` — xavfsizlik-auditi topilmasi (mijoz,
2026-09-24, kpgen CLAUDE.md §48 #8). `KPGEN_PROXY_API_KEY`
sozlanmagan bo'lsa tekshiruv NOOP (bosqichma-bosqich deploy xavfsiz
bo'lishi uchun) — mavjud barcha boshqa testlar (`test_vision.py` va
h.k.) shu holatga tayanadi, ULARGA TEGILMAYDI.
"""

import base64
import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app

client = TestClient(app)


def _sample_image_base64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_kalit_sozlanmagan_bolsa_headersiz_ham_otadi(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: None)
    with patch("app.main.ask_claude", return_value="Вентиляторы"):
        resp = client.post("/classify", json={"text": "Вентилятор радиальный"})
    assert resp.status_code == 200


def test_kalit_sozlangan_headersiz_sorov_401(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")
    resp = client.post("/classify", json={"text": "Вентилятор радиальный"})
    assert resp.status_code == 401


def test_kalit_sozlangan_notogri_header_401(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")
    resp = client.post(
        "/classify", json={"text": "test"}, headers={"X-KPGen-Api-Key": "notogri"}
    )
    assert resp.status_code == 401


def test_kalit_sozlangan_togri_header_otadi(monkeypatch):
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")
    with patch("app.main.ask_claude", return_value="Вентиляторы"):
        resp = client.post(
            "/classify", json={"text": "test"}, headers={"X-KPGen-Api-Key": "sekret-kalit"}
        )
    assert resp.status_code == 200


def test_health_kalit_talab_qilmaydi(monkeypatch):
    """`/health` — `dependencies=[Depends(_require_api_key)]` UMUMAN
    qo'llanmagan, monitoring/soglik-tekshiruvi kalit bilmasa ham
    ishlashi kerak."""
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")
    resp = client.get("/health")
    assert resp.status_code == 200


def test_barcha_tort_endpoint_kalit_talab_qiladi(monkeypatch):
    """Regressiya-qulf — kelajakda yangi endpoint qo'shilganda ham,
    bu to'rttasi (allaqachon mavjud, pullik) unutilib qolmasligi
    uchun ANIQ, bittalab tekshiriladi."""
    monkeypatch.setattr("app.main.config.get_proxy_api_key", lambda: "sekret-kalit")

    resp = client.post("/classify", json={"text": "test"})
    assert resp.status_code == 401

    resp = client.post(
        "/vision", json={"image_base64": _sample_image_base64(), "context": "test"}
    )
    assert resp.status_code == 401

    resp = client.post(
        "/dwg_spec",
        json={"elements": [{"text": "test", "x": 0.0, "y": 0.0, "layer": "0"}]},
    )
    assert resp.status_code == 401

    resp = client.post(
        "/read_spec",
        json={
            "image_base64": _sample_image_base64(),
            "sozlar": [{"id": "w1", "matn": "test", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}],
            "sahifa_raqami": 1,
        },
    )
    assert resp.status_code == 401
