"""Anthropic API chaqiruvi — xatolar tushunarli xabarga aylantiriladi,
server hech qachon qulamaydi (chaqiruvchi tomon HTTP xato qaytaradi)."""

import logging

import anthropic

from app.config import (
    DWG_SPEC_MAX_TOKENS,
    DWG_SPEC_MODEL_NAME,
    MODEL_NAME,
    READ_SPEC_MAX_TOKENS,
    READ_SPEC_MODEL_NAME,
    VISION_MODEL_NAME,
    get_api_key,
)

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
        # Faza-45-topshiriq §B (haqiqiy xato #2, Мимар sinovida topilgan,
        # 2026-09-08): murakkab so'rovlarda (uzun DWG-elementlar ro'yxati)
        # model o'zi "extended thinking"ni yoqib yuborishi mumkin edi —
        # butun `max_tokens` byudjeti o'ylashga sarflanib, yakuniy JSON
        # javobiga o'rin qolmagan (faqat ThinkingBlock, matn-blok YO'Q).
        # Bizga bu yerda fikrlash jarayoni emas, to'g'ridan-to'g'ri
        # tuzilgan javob kerak — shuning uchun thinking ANIQ o'chiriladi
        # (xarajat/vaqt ham shu bilan bashorat qilinadigan bo'ladi).
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            thinking={"type": "disabled"},
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
- "belgi": jadvalning "Поз." (pozitsiya) ustunidagi qisqa belgi/kod, agar mavjud bo'lsa (masalan "КЭ1", "В1", "К1, К2") — bu ELEMENTLAR RO'YXATIDA AYNAN shu matn sifatida bo'lishi SHART; bunday belgi umuman yo'q/aniqlanmasa — null
- "manba_matnlar": ushbu pozitsiyani qurish uchun ISHLATGAN elementlaring matnini AYNAN, SO'ZMA-SO'Z (o'zgartirmasdan, tarjima qilmasdan) ro'yxat qilib ber (shu jumladan "belgi" qiymatining o'zi ham shu ro'yxatda bo'lsin) — bu MAJBURIY, tekshiruv uchun kerak

QOIDALAR:
- Bir xil jadval bir necha marta takrorlansa (masalan bir nechta bino/varaq uchun) — HAR bir takrorlanishni ALOHIDA pozitsiya sifatida ber, birlashtirma.
- Faqat berilgan elementlar ro'yxatidagi matnlardan foydalan — hech narsani o'zingdan qo'shma yoki o'ylab topma.
- "manba_matnlar"dagi har bir satr ro'yxatda AYNAN shunday (harfma-harf) bo'lishi SHART.
- Spetsifikatsiyaga aloqasi yo'q matnlarni (sarlavha, shtamp, o'lchamlar, umumiy izohlar) e'tiborsiz qoldir.

Javobing FAQAT xom JSON bo'lsin — kirish so'zisiz, izohsiz, tushuntirishsiz, markdown kod blokisiz (```json yozma). Birinchi belgi javobingda darhol "{{" bo'lishi shart:
{{"positions": [{{"naim": "...", "ed": "...", "kol": 2, "belgi": "КЭ1", "manba_matnlar": ["...", "..."]}}, ...]}}

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


# Faza-72-topshiriq (mijoz, 2026-09-11): PDF/Excel spetsifikatsiya
# sahifasini AI yordamida o'qish — rasm (joylashuv/tuzilma uchun) +
# xom so'z-koordinata matni (aniq belgilar uchun) BIRGA yuboriladi.
# T1 (model faqat ko'chiradi, hisoblamaydi), T2 (har qiymat manbada
# tekshiriladi — bu ISHONCH TEKSHIRUVI kpgen tomonida, `ai/read_spec.py`,
# bu yerda EMAS), T3 (noaniq — null, taxmin emas) — CLAUDE.md/topshiriq
# talablari, promptning o'zida takrorlangan.
_READ_SPEC_PROMPT = """Senga qurilish/muhandislik loyihasining spetsifikatsiya sahifasi beriladi — ikki ko'rinishda:
1) sahifaning RASMI (joylashuv, jadval chizig'i, qatorlar tuzilmasini ko'rish uchun);
2) o'sha sahifadagi barcha SO'ZLARNING XOM MATNI, har birining koordinatasi bilan (aniq belgilarni o'qish uchun — rasmda ba'zan belgi noaniq ko'rinishi mumkin, matn har doim aniq).

Bu — GOST uslubidagi ventilyatsiya/isitish/santexnika spetsifikatsiyasi (odatda ustunlar: Поз. / Наименование и техническая характеристика / Тип, марка / Код / Завод-изготовитель / Единица измерения / Количество / Масса единицы / Примечание — lekin aniq ustun tarkibi va tartibi fayldan-faylga farq qiladi, RASMDAN sarlavhani o'qib aniqla).

═══ QATOR TUZILMASI — MUHIM ═══

Bitta pozitsiya bir NECHTA jismoniy qatorga bo'lingan bo'lishi mumkin:
  - Поз. + nom BIRINCHI qatorda, miqdor OXIRGI qatorda (masalan:
    "1 | Радиатор отопительный биметаллический" / "10 секций | шт. | 1")
  - yoki: nom / texnik tavsif (L=, P=, N=, Q= kabi parametrlar, bir
    necha qatorga bo'linishi mumkin) / tip+birlik+miqdor OXIRGI qatorda
  - "1.1)", "1.2)", ">" bilan boshlangan qatorlar — OLDINGI pozitsiyaning
    tarkibi/davomi, YANGI pozitsiya EMAS

Bunday holatlarda barcha jismoniy qatorlarni BITTA pozitsiyaga birlashtir,
lekin HAR BIR jismoniy qator matnini "davom_qatorlari" ro'yxatida ALOHIDA,
XOM holicha (o'zgartirmasdan) saqlab qo'y — bu keyinchalik manba bilan
tekshirish uchun ishlatiladi.

Nom BILAN tanish emas — quyidagilar pozitsiya EMAS:
  - bo'lim sarlavhasi (faqat nom, miqdorsiz — masalan "Вентиляция",
    "Оборудования для отопления")
  - sahifa sarlavhasi takrori (ustun nomlari — "Поз.", "Наименование...")
  - shtamp maydoni ("Изм.", "Кол.уч.", "Лист", "Инв.№ подл.", imzo maydoni)

═══ MUHIM QOIDALAR — BUZILMASIN ═══

- "L=NNN м³/ч" — bu HAVO SARFI (расход воздуха), FIZIK UZUNLIK EMAS.
  Hech qachon uzunlik sifatida talqin qilma.
- "Масса единицы, kg" ustuni — bu OG'IRLIK, miqdor (kol) EMAS. Alohida
  "massa" maydoniga yoz, "kol"ga aralashtirma.
- "kol" (Количество) ustunidagi qiymatni XOM MATN sifatida ber — SON
  SIFATIDA EMAS. Agar u "25/65" kabi ikki qiymatli bo'lsa — aynan
  "25/65" deb yoz, qaysi son kerakligini HAL QILMA (bu boshqa dastur
  qismining vazifasi). Vergul/nuqta, bo'shliq — manbadagidek qoldir.
- HECH NARSANI hisoblama (yig'indi, ko'paytma, birlik o'girish),
  HECH NARSANI tozalama yoki "chiroyli" qilma. Manbada qanday yozilgan
  bo'lsa — xuddi shunday ko'chir (imlo xatosi, qisqartma, katta/kichik
  harf — o'zgarishsiz).
- Bir xil nom bir necha marta takrorlansa (masalan bir nechta bir xil
  radiator, turli seksiya soni bilan) — HAR birini ALOHIDA pozitsiya
  sifatida ber, birlashtirma.

═══ ISHONCHSIZ HOLAT ═══

Agar biror maydonni (naim/tip/ed/kol/prim) ANIQ va ishonchli o'qiy
olmasang — o'sha maydonga null qo'y, "izoh"da sababini qisqacha yoz
(masalan "raqam noaniq, qora dog' bilan qoplangan"). TAXMIN QILMA —
noaniq qiymatdan ko'ra bo'sh maydon yaxshiroq.

═══ JAVOB FORMATI ═══

Javobing FAQAT xom JSON bo'lsin — kirish so'zisiz, izohsiz, markdown
kod blokisiz (```json yozma). Birinchi belgi javobingda darhol "{{"
bo'lishi shart:

{{
  "sahifa": {sahifa_raqami},
  "bolimlar": [
    {{
      "nom": "Вентиляция / Воздуховоды",
      "qatorlar": [
        {{
          "poz": "1",
          "naim": "Радиатор отопительный биметаллический 10 секций",
          "tip": null,
          "ed": "шт.",
          "kol": "1",
          "massa": null,
          "prim": null,
          "davom_qatorlari": ["Радиатор отопительный биметаллический", "10 секций"],
          "manba_qator_raqamlari": [4, 5],
          "ishonch": "yuqori",
          "izoh": null
        }}
      ]
    }}
  ],
  "otkazib_yuborilgan": [
    {{"matn": "Изм. Кол.уч. Лист № докум. Подп. Дата", "sabab": "shtamp"}}
  ]
}}

Agar sahifada hech qanday spetsifikatsiya jadvali topilmasa:
{{"sahifa": {sahifa_raqami}, "bolimlar": [], "otkazib_yuborilgan": []}}

═══ KIRISH MA'LUMOTLARI ═══

Sahifa raqami: {sahifa_raqami}

Avvalgi sahifadan kontekst (agar bo'lsa — bo'lim/pozitsiya jadval
davom etayotganini bildiradi): {avvalgi_kontekst}

So'zlar (matn, x0, y0, x1, y1 — PDF koordinata, chapdan-o'ngga,
yuqoridan-pastga):
{sozlar}"""


def ask_claude_read_spec(
    image_base64: str,
    sozlar_tsv: str,
    *,
    sahifa_raqami: int,
    avvalgi_kontekst: str = "yo'q (birinchi sahifa)",
    max_tokens: int = READ_SPEC_MAX_TOKENS,
) -> str:
    """Sahifa rasmi (base64 PNG) + so'z-koordinata matnini modelga
    yuboradi, xom JSON-matnni qaytaradi (parsing/tekshirish chaqiruvchi
    — `main.py` server-tomon shakl-tekshiruvi, ASOSIY manba-tekshiruvi
    esa kpgen tomonida, `ai/read_spec.py`)."""
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
                    "text": _READ_SPEC_PROMPT.format(
                        sahifa_raqami=sahifa_raqami,
                        avvalgi_kontekst=avvalgi_kontekst,
                        sozlar=sozlar_tsv,
                    ),
                },
            ],
        }
    ]
    return _call_anthropic(model=READ_SPEC_MODEL_NAME, messages=messages, max_tokens=max_tokens)
