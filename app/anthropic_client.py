"""Anthropic API chaqiruvi — xatolar tushunarli xabarga aylantiriladi,
server hech qachon qulamaydi (chaqiruvchi tomon HTTP xato qaytaradi)."""

import anthropic

from app.config import MODEL_NAME, get_api_key


class ProxyError(Exception):
    """Chaqiruvchi (main.py) tomonidan tushunarli JSON xatoga aylantiriladi."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def ask_claude(prompt: str, *, max_tokens: int = 100) -> str:
    """`prompt`ni Anthropic API'ga (MODEL_NAME) yuboradi, matn javobini
    qaytaradi.

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
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
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
