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
