"""`_call_anthropic()` testlari — HAQIQIY tarmoqqa chiqmasdan, mock
bilan.

Faza-45-topshiriq §B (mijoz, 2026-09-08): haqiqiy Мимар sinovida
topilgan xato — murakkab so'rovlarda (uzun DWG-elementlar ro'yxati)
Anthropic API avtomatik "extended thinking" ishlatishi mumkin,
natijada `response.content[0]` matn-blok EMAS, `ThinkingBlock` bo'lib
qoladi (`.text` maydoni yo'q) — `_call_anthropic()` shu holatda
matnni TOPA OLMAY qulagan edi ("'ThinkingBlock' object has no
attribute 'text'"). Bu testlar aynan shu ssenariyni sinaydi."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx2
import pytest

from app.anthropic_client import ProxyError, ask_claude


def _fake_usage():
    return SimpleNamespace(input_tokens=100, output_tokens=20)


class _FakeThinkingBlock:
    """Haqiqiy `anthropic.types.ThinkingBlock`ning `.text` maydoni YO'Q
    — faqat `.thinking`."""

    def __init__(self, thinking: str):
        self.thinking = thinking


class _FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


def _fake_client(content_blocks, stop_reason="end_turn"):
    fake_response = SimpleNamespace(content=content_blocks, usage=_fake_usage(), stop_reason=stop_reason)
    fake_messages = MagicMock()
    fake_messages.create.return_value = fake_response
    return SimpleNamespace(messages=fake_messages)


def test_oddiy_matn_blok_togri_oqiladi():
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch(
            "app.anthropic_client.anthropic.Anthropic",
            return_value=_fake_client([_FakeTextBlock("Вентиляторы")]),
        ):
            result = ask_claude("test prompt")

    assert result == "Вентиляторы"


def test_thinking_blok_oldida_bolsa_ham_matn_topiladi():
    """Haqiqiy topilgan xato: `content[0]` — ThinkingBlock, `content[1]`
    — haqiqiy matn. Endi to'g'ri o'qilishi kerak."""
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch(
            "app.anthropic_client.anthropic.Anthropic",
            return_value=_fake_client(
                [_FakeThinkingBlock("Men bu haqda o'ylayapman..."), _FakeTextBlock("Вентиляторы")]
            ),
        ):
            result = ask_claude("test prompt")

    assert result == "Вентиляторы"


def test_faqat_thinking_blok_matn_yoq_xato():
    """Javobda umuman matn-blok bo'lmasa (faqat thinking) — tushunarli
    `ProxyError`, xom Python xatosi EMAS."""
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch(
            "app.anthropic_client.anthropic.Anthropic",
            return_value=_fake_client([_FakeThinkingBlock("faqat o'ylash, javob yo'q")]),
        ):
            with pytest.raises(ProxyError, match="matn-blok topilmadi"):
                ask_claude("test prompt")


def test_thinking_aniq_ochirilgan_holda_sorov_yuboriladi():
    """Ildiz sabab (Мимар sinovida topilgan #2-xato): model o'zi
    "extended thinking"ni yoqib, butun `max_tokens` byudjetini
    o'ylashga sarflab, matn-blok umuman qoldirmasligi mumkin edi.
    Endi HAR bir so'rovda `thinking={"type": "disabled"}` ANIQ
    uzatilishi shart — shu bilan bu butun xato sinfi oldindan
    oldini olinadi (byudjet to'liq yakuniy javobga ketadi)."""
    fake_client = _fake_client([_FakeTextBlock("Вентиляторы")])
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch("app.anthropic_client.anthropic.Anthropic", return_value=fake_client):
            ask_claude("test prompt")

    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["thinking"] == {"type": "disabled"}


def _real_api_status_error(status_code: int, error_message: str) -> anthropic.APIStatusError:
    """Haqiqiy Anthropic SDK'ning `_make_status_error_from_response()`
    bilan BIR XIL formatda xato yasaydi (`err_msg = f"Error code: {code}
    - {body}"`) — mock emas, real xatti-harakat, aks holda
    "credit balance" matnini ushlash mantig'i sinalmagan taxmin
    bo'lib qolardi."""
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": error_message}}
    resp = httpx2.Response(status_code, request=req, json=body)
    err_msg = f"Error code: {status_code} - {body}"
    return anthropic.APIStatusError(err_msg, response=resp, body=body)


def test_kredit_balansi_tugaganda_aniq_402_xato():
    """Faza-72, Band 1b (mijoz, 2026-09-12): sibir_ventilyatsiya
    010-015 va Band-5'ning kaskadli 400-xatolari — sababi Anthropic
    hisobining kredit balansi tugagani edi. Bu boshqa 400'lardan
    (masalan noto'g'ri so'rov) TUBDAN farqli (qayta urinish yordam
    bermaydi) — endi ALOHIDA, aniq status (402) bilan ushlanadi."""
    exc = _real_api_status_error(400, "Your credit balance is too low to access the Claude API.")
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch("app.anthropic_client.anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create.side_effect = exc
            with pytest.raises(ProxyError, match="kredit") as exc_info:
                ask_claude("test prompt")
    assert exc_info.value.status_code == 402


def test_boshqa_400_xato_kredit_bilan_aralashtirilmaydi():
    """Kredit-bog'liq bo'lmagan 400 (masalan noto'g'ri so'rov formati)
    — eski, umumiy 502 yo'lidan o'tishi kerak, 402 EMAS."""
    exc = _real_api_status_error(400, "messages: at least one message is required")
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch("app.anthropic_client.anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create.side_effect = exc
            with pytest.raises(ProxyError) as exc_info:
                ask_claude("test prompt")
    assert exc_info.value.status_code == 502


def test_400_xato_matni_toliq_xabarga_qoshiladi():
    """Round-8-topshiriq (mijoz, 2026-09-19, jonli xato — 'блок 2:
    ошибка ИИ (502): Anthropic API xato qaytardi: 400' — sabab hech
    qayerda ko'rinmasdi). Endi Anthropic'ning o'z xato-matni ProxyError
    xabariga qo'shiladi — chaqiruvchi tomon (kpgen «Отчёт») buni
    ko'rishi kerak, faqat qattiq status-kod EMAS."""
    exc = _real_api_status_error(400, "messages.0.content.0.image.source.base64.data: invalid base64 data")
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch("app.anthropic_client.anthropic.Anthropic") as mock_client_cls:
            mock_client_cls.return_value.messages.create.side_effect = exc
            with pytest.raises(ProxyError, match="invalid base64 data") as exc_info:
                ask_claude("test prompt")
    assert exc_info.value.status_code == 502


def test_max_tokens_chegarasida_kesilgan_javob_xato_beradi():
    """Faza-72, 3-bosqich yakunida topilgan haqiqiy xato (mijoz,
    2026-09-12): `stop_reason == "max_tokens"` bo'lsa, matn ko'pincha
    yarim-JSON — bu ILGARI boshqa har qanday "buzuq JSON" bilan bir xil
    ko'rinardi. Endi ANIQ, alohida ProxyError bilan rad etiladi."""
    with patch("app.anthropic_client.get_api_key", return_value="fake-key"):
        with patch(
            "app.anthropic_client.anthropic.Anthropic",
            return_value=_fake_client([_FakeTextBlock('{"sahifa": 1, "bolimlar": [{"nom"')], stop_reason="max_tokens"),
        ):
            with pytest.raises(ProxyError, match="max_tokens"):
                ask_claude("test prompt")
