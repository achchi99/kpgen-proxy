"""Anthropic API chaqiruvi — xatolar tushunarli xabarga aylantiriladi,
server hech qachon qulamaydi (chaqiruvchi tomon HTTP xato qaytaradi)."""

import logging

import anthropic

from app.config import DWG_SPEC_MAX_TOKENS, DWG_SPEC_MODEL_NAME, MODEL_NAME, VISION_MODEL_NAME, get_api_key

_log = logging.getLogger("kpgen_proxy")


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

    # Faza-45-topshiriq §B (mijoz, 2026-09-08, "xarajat nazorat qilinsin"):
    # har chaqiruv token-sarfi logga yoziladi — systemd journal orqali
    # ko'rinadi, alohida monitoring kerak emas.
    usage = getattr(response, "usage", None)
    if usage is not None:
        _log.info(
            "anthropic chaqiruvi: model=%s in_tokens=%s out_tokens=%s",
            model, usage.input_tokens, usage.output_tokens,
        )

    # Faza-45-topshiriq §B (haqiqiy xato, Мимар sinovida topilgan, 2026-
    # 09-08): `content[0]` HAR DOIM matn-blok deb taxmin qilingan edi —
    # lekin murakkab so'rovlarda (masalan uzun DWG-elementlar ro'yxati)
    # model avtomatik "extended thinking" ishlatishi mumkin, natijada
    # `content[0]` — `.text` MAYDONI YO'Q `ThinkingBlock`. Endi ro'yxatdan
    # BIRINCHI haqiqiy matn-blok qidiriladi (qaysi index'da bo'lishidan
    # qat'i nazar).
    for block in response.content:
        text = getattr(block, "text", None)
        if text is not None:
            return text.strip()
    raise ProxyError("Anthropic API javobida matn-blok topilmadi", status_code=502)


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


# Faza-45-topshiriq §B (mijoz, 2026-09-08): DWG'da determinal o'qish
# muvaffaqiyatsiz bo'lganda (spetsifikatsiya topilmadi, yoki tanlangan
# qatlam fayldagi eng kattasidan sezilarli kichik) — xom TEXT/MTEXT
# elementlari (matn+koordinata+qatlam, ALLAQACHON DXF'dan o'qilgan,
# qo'shimcha render/vision kerak emas) modelga beriladi, jadval
# tiklanadi. Har pozitsiya QAYSI aniq manba-matn(lar)dan kelganini
# ("manba_matnlar") ko'rsatishi SHART — kpgen tomonida (`ai/dwg_ai.py`)
# bu iqtiboslar asl elementlar ro'yxati bilan (matn VA koordinata
# yaqinligi bo'yicha) tekshiriladi, model "o'ylab topgan" raqam hech
# qachon КП'ga tushmasligi kerak (mijozning qat'iy sharti).
_DWG_SPEC_PROMPT = """Senga CAD chizmasidan (DXF) xom matn elementlari beriladi — har birining matni, x/y koordinatasi va qatlam nomi. Bu matnlar orasida qurilish/muhandislik uskunalar spetsifikatsiyasi jadvali bor (odatda ustunlar: Поз./Наименование/Единица измерения/Количество yoki shunga o'xshash), lekin u boshqa chizma matnlari (sarlavhalar, o'lchamlar, izohlar, shtamp) bilan aralashgan va bir nechta qatlamga bo'lingan bo'lishi mumkin.

Vazifang: FAQAT spetsifikatsiya jadvali qatorlarini toping va JSON qaytaring. Har bir pozitsiya uchun:
- "naim": jihoz/material nomi (texnik tavsif bilan, agar bo'lsa)
- "ed": o'lchov birligi (masalan "шт", "компл.", "м")
- "kol": miqdor (son) — agar ANIQ va ishonchli topa olmasang, null qo'y (TAXMIN QILMA)
- "manba_matnlar": ushbu pozitsiyani qurish uchun ISHLATGAN elementlaring matnini AYNAN, SO'ZMA-SO'Z (o'zgartirmasdan, tarjima qilmasdan) ro'yxat qilib ber — bu MAJBURIY, tekshiruv uchun kerak

QOIDALAR:
- Bir xil jadval bir necha marta takrorlansa (masalan bir nechta bino/varaq uchun) — HAR bir takrorlanishni ALOHIDA pozitsiya sifatida ber, birlashtirma.
- Faqat berilgan elementlar ro'yxatidagi matnlardan foydalan — hech narsani o'zingdan qo'shma yoki o'ylab topma.
- "manba_matnlar"dagi har bir satr ro'yxatda AYNAN shunday (harfma-harf) bo'lishi SHART.
- Spetsifikatsiyaga aloqasi yo'q matnlarni (sarlavha, shtamp, o'lchamlar, umumiy izohlar) e'tiborsiz qoldir.

Faqat quyidagi JSON formatida javob ber, boshqa hech qanday matn yozma:
{{"positions": [{{"naim": "...", "ed": "...", "kol": 2, "manba_matnlar": ["...", "..."]}}, ...]}}

Agar hech qanday spetsifikatsiya jadvali topilmasa: {{"positions": []}}

Elementlar (matn\tx\ty\tqatlam):
{elements}"""


def ask_claude_dwg_spec(elements_tsv: str, *, max_tokens: int = DWG_SPEC_MAX_TOKENS) -> str:
    """`elements_tsv` — "matн\\tx\\ty\\tqatlam" qatorlari (bitta element
    bitta qator). Xom JSON-matnni qaytaradi (parsing/tekshirish
    chaqiruvchi — `main.py` — vazifasi)."""
    return _call_anthropic(
        model=DWG_SPEC_MODEL_NAME,
        messages=[{"role": "user", "content": _DWG_SPEC_PROMPT.format(elements=elements_tsv)}],
        max_tokens=max_tokens,
    )
