"""Anthropic API chaqiruvi — xatolar tushunarli xabarga aylantiriladi,
server hech qachon qulamaydi (chaqiruvchi tomon HTTP xato qaytaradi)."""

import anthropic

from app.config import MODEL_NAME, VISION_MODEL_NAME, get_api_key


class ProxyError(Exception):
    """Chaqiruvchi (main.py) tomonidan tushunarli JSON xatoga aylantiriladi."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _call_anthropic(*, model: str, messages: list[dict], max_tokens: int) -> str:
    """Anthropic'ga chaqiruv — matn ham, vision ham shu orqali o'tadi,
    xato-turlari bir xil tarzda ProxyError'ga aylantiriladi (DRY).

    Raises:
        ProxyError: kalit yo'q/noto'g'ri, tarmoq xatosi, yoki Anthropic
            xato qaytarsa — har doim inson o'qiy oladigan xabar bilan.
    """
    api_key = get_api_key()
    if not api_key:
        raise ProxyError(
            "ANTHROPIC_API_KEY topilmadi (/etc/kpgen-secrets.env tekshiring)",
            status_code=500,
        )

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(model=model, max_tokens=max_tokens, messages=messages)
    except anthropic.AuthenticationError as exc:
        raise ProxyError("Anthropic API kalit noto'g'ri yoki muddati o'tgan", status_code=500) from exc
    except anthropic.RateLimitError as exc:
        raise ProxyError("Anthropic API so'rov chegarasi tugadi, keyinroq urinib ko'ring", status_code=429) from exc
    except anthropic.APIConnectionError as exc:
        raise ProxyError("Anthropic API bilan bog'lanib bo'lmadi (tarmoq xatosi)", status_code=502) from exc
    except anthropic.APIStatusError as exc:
        raise ProxyError(f"Anthropic API xato qaytardi: {exc.status_code}", status_code=502) from exc
    except Exception as exc:  # kutilmagan holat — server baribir qulamasin
        raise ProxyError(f"Kutilmagan xato: {exc}", status_code=500) from exc

    if not response.content:
        raise ProxyError("Anthropic API bo'sh javob qaytardi", status_code=502)

    return response.content[0].text.strip()


def ask_claude(prompt: str, *, max_tokens: int = 100) -> str:
    """`prompt`ni Anthropic API'ga (MODEL_NAME, matn) yuboradi, javobni qaytaradi."""
    return _call_anthropic(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


_VISION_PROMPT = (
    "Bu rasmda bitta katak bor — texnik jadvaldagi 'Кол-во' (miqdor) "
    "katagi, CAD chizmasidan olingan (vektor shrift, OCR emas). "
    "Kontekst: {context}\n\n"
    "Faqat katakdagi RAQAMNING O'ZINI qaytar (masalan \"39\" yoki \"6.3\"), "
    "boshqa hech qanday so'z, birlik yoki izoh yozma. "
    "Agar raqamni aniq va ishonchli o'qiy olmasang — faqat bitta so'z: null"
)


def ask_claude_vision(image_base64: str, context: str, *, max_tokens: int = 20) -> str:
    """Rasmni (base64, PNG) Anthropic vision API'ga (VISION_MODEL_NAME)
    yuboradi, model javobini (xom matn — "39" yoki "null") qaytaradi.

    Javobni RAQAM/`null` ekanligini tekshirish — bu funksiya EMAS,
    chaqiruvchi (`main.py`) vazifasi (server-tomon qat'iy validatsiya).
    """
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_base64,
                    },
                },
                {
                    "type": "text",
                    "text": _VISION_PROMPT.format(context=context),
                },
            ],
        }
    ]
    return _call_anthropic(model=VISION_MODEL_NAME, messages=messages, max_tokens=max_tokens)
