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

# Faza-72, Band 1a (mijoz, 2026-09-12): oxirgi chaqiruvning token-sarfi
# — `main.py`ning `/read_spec` javobiga qo'shiladi (`ReadSpecResponse.
# usage`), shunda kpgen tomoni (`run_shadow.py --max-xarajat`) HAQIQIY
# xarajatni real vaqtda kuzatib, chegaraga yetganda to'xtay oladi
# (taxminga tayanmasdan).
LAST_USAGE: dict | None = None


class ProxyError(Exception):
    """Chaqiruvchi (main.py) tomonidan tushunarli JSON xatoga aylantiriladi."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _call_anthropic(
    *, model: str, messages: list[dict], max_tokens: int, system: list[dict] | None = None
) -> str:
    """Anthropic'ga chaqiruv — matn ham, vision ham shu orqali o'tadi,
    xato-turlari bir xil tarzda ProxyError'ga aylantiriladi (DRY).

    `system` — Faza-72 Band 2 (prompt caching): berilsa, `cache_control`
    belgilangan content-bloklar ro'yxati sifatida to'g'ridan-to'g'ri
    Anthropic SDK'ga uzatiladi (`/read_spec`da ishlatiladi; boshqa
    chaqiruvchilar — `ask_claude`/`ask_claude_vision`/`ask_claude_dwg_
    spec` — bu parametrni ishlatmaydi, `None` qoladi).

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
        create_kwargs = dict(model=model, max_tokens=max_tokens, messages=messages, thinking={"type": "disabled"})
        if system is not None:
            create_kwargs["system"] = system
        response = client.messages.create(**create_kwargs)
    except anthropic.AuthenticationError as exc:
        raise ProxyError("Anthropic API kalit noto'g'ri yoki muddati o'tgan", status_code=500) from exc
    except anthropic.RateLimitError as exc:
        raise ProxyError("Anthropic API so'rov chegarasi tugadi, keyinroq urinib ko'ring", status_code=429) from exc
    except anthropic.APIConnectionError as exc:
        raise ProxyError("Anthropic API bilan bog'lanib bo'lmadi (tarmoq xatosi)", status_code=502) from exc
    except anthropic.APIStatusError as exc:
        # Faza-72, 3-bosqich yakunida topilgan haqiqiy xato (mijoz,
        # 2026-09-12): sibir_ventilyatsiya 010-015 va Band-5'ning
        # sunon/002'dan boshlab yiqilishi — ikkalasida ham bitta sekin
        # 400, KEYIN barcha keyingi so'rovlar instant 400 bilan
        # yiqilardi. Sabab endi aniqlandi: Anthropic hisobining kredit
        # balansi tugagan edi (400 xato matnida "credit balance"
        # iborasi bor) — bu boshqa har qanday 400'dan (masalan noto'g'ri
        # so'rov formati) TUBDAN farqli: qayta urinish yordam bermaydi,
        # hisobni to'ldirish kerak. Endi ALOHIDA, aniq turkum bilan
        # ushlanadi — log'da ham, javobda ham darhol ko'rinadi.
        xabar_matni = str(getattr(exc, "message", "") or str(exc))
        if "credit balance" in xabar_matni.lower():
            _log.error("ANTHROPIC KREDIT BALANSI TUGADI: %s", xabar_matni)
            raise ProxyError(
                "Anthropic hisobida kredit balansi yetarli emas — hisobni to'ldiring",
                status_code=402,
            ) from exc
        # Round-8-topshiriq (mijoz, 2026-09-19, jonli xato — "блок 2:
        # ошибка ИИ (502): Anthropic API xato qaytardi: 400"): xabar
        # matni faqat status-kod bilan cheklangan edi, sababning o'zi
        # (masalan "image exceeds 5 MB maximum", "invalid base64 data",
        # boshqa noto'g'ri so'rov sababi) hech qayerga chiqmasdi — na
        # logga, na chaqiruvchiga (kpgen'ning «Отчёт» varag'idagi
        # bolak['sabab']). Endi ikkalasiga ham yoziladi (500 belgigacha,
        # log to'lib ketmasin) — CLAUDE.md §14 (Faza-68) ruhi bilan bir
        # xil: "biz ko'r holda ishlamaymiz" endi bu yo'lga ham tegishli.
        _log.error("Anthropic API xato (status=%s): %s", exc.status_code, xabar_matni[:500])
        raise ProxyError(
            f"Anthropic API xato qaytardi: {exc.status_code} — {xabar_matni[:300]}", status_code=502
        ) from exc
    except Exception as exc:  # kutilmagan holat — server baribir qulamasin
        raise ProxyError(f"Kutilmagan xato: {exc}", status_code=500) from exc

    if not response.content:
        raise ProxyError("Anthropic API bo'sh javob qaytardi", status_code=502)

    # Faza-72, 3-bosqich yakunida topilgan haqiqiy xato (mijoz,
    # 2026-09-12): javob `max_tokens` chegarasida KESILGAN bo'lishi
    # mumkin (`stop_reason == "max_tokens"`) — bunday holatda matn
    # ko'pincha yarim-JSON, `json.loads()` xato beradi, lekin bu ILGARI
    # boshqa har qanday "model buzuq JSON qaytardi" holati bilan bir xil
    # ko'rinardi (aniq sabab yo'qolardi). Endi ANIQ, alohida xabar bilan
    # rad etiladi — chaqiruvchi tomon buni "javob kesildi, max_tokens
    # kam" deb aniq izohlay oladi (masalan bo'lak hajmini kichraytirish
    # kerakligini bildiradi).
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ProxyError(
            f"Anthropic javobi max_tokens ({max_tokens}) chegarasida kesildi",
            status_code=502,
        )

    # Faza-45-topshiriq §B (mijoz, 2026-09-08, "xarajat nazorat qilinsin"):
    # har chaqiruv token-sarfi logga yoziladi — systemd journal orqali
    # ko'rinadi, alohida monitoring kerak emas.
    usage = getattr(response, "usage", None)
    if usage is not None:
        _log.info(
            "anthropic chaqiruvi: model=%s in_tokens=%s out_tokens=%s",
            model, usage.input_tokens, usage.output_tokens,
        )
        global LAST_USAGE
        LAST_USAGE = {
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            # Faza-72, Band 2 (prompt caching) — mavjud bo'lsa qo'shiladi,
            # bo'lmasa 0 (SDK versiyasi/keshlanmagan so'rov).
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        }

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

═══ MANBA-ID — ENG MUHIM QOIDA ═══

Pastda "KIRISH MA'LUMOTLARI"da har SO'Z/KATAK o'zining o'zgarmas ID'si
bilan beriladi (birinchi ustun — masalan "w42" yoki "P6"), undan keyin
matni va koordinatasi keladi.

Har chiqish qatori uchun "manba" degan JSON-obyekt qaytarishing SHART —
har bir maydon (naim/tip/ed/kol/massa/prim) qaysi ANIQ ID(lar)dan
olinganini ko'rsatadi:

  "manba": {{"naim": ["w12","w13"], "tip": null, "ed": "w20", "kol": "w21", "massa": null, "prim": null}}

QOIDALAR:
- "naim" — ID RO'YXATI bo'lishi mumkin (pozitsiya bir nechta so'z/
  katakdan yig'ilgan bo'lsa — qo'shni qatorlar HAM, qo'shni ustunlar
  HAM bo'lishi mumkin). Boshqa maydonlar odatda BITTA ID (kerak bo'lsa
  ro'yxat ham bo'lishi mumkin).
- Maydon qiymati null BO'LMASA — o'sha maydon uchun ID(lar) HAM
  bo'lishi SHART. Qiymat null bo'lsa — manba ID ham null (yoki umuman
  yozmasang ham bo'ladi).
- ID FAQAT pastda berilgan ro'yxatdan bo'lishi mumkin — o'zingdan ID
  o'ylab topma, boshqa pozitsiyaning ID'sini "qarzga" olma (har bir ID
  FAQAT o'ziga tegishli qiymatni tasdiqlash uchun ishlatiladi — bitta
  ID'ni ikki xil pozitsiyada ishlatsang, IKKALASI HAM rad etiladi).
- "naim"ga qo'shgan HAR BIR so'z manba-ID(lar) matnida SO'ZMA-SO'Z
  bo'lishi kerak (fabrikatsiyaga qarshi himoya) — lekin "naim"ning o'zi
  ID matnining AYNAN nusxasi bo'lishi shart emas (masalan siyoh
  belgilarini/tinish belgilarini birlashtirib yozishing mumkin).
- "naim" FAQAT o'ziga ko'rsatilgan ID(lar)dagi so'zlardan tuzilsin.
  Boshqa, O'XSHASH qatorlarda ko'rgan NAQSHINGGA (masalan "тип, DN
  N" formatiga) qarab so'z QO'SHMA — har bir pozitsiya o'z manba
  matniga qarab, MUSTAQIL yoziladi.

  Misol (haqiqiy xato, live sinovda topilgan): boshqa qatorlarda
  "Шаровой кран, DN 15" kabi "DN" bilan yozilgan bo'lsa-da, joriy
  qator manba-katagida FAQAT "Манометр" va "15" bor, "DN" so'zi
  UMUMAN YO'Q:
  NOTO'G'RI: "naim": "Манометр, DN 15"  ← "DN" boshqa qatorlar naqshidan olingan, manbada yo'q
  TO'G'RI:   "naim": "Манометр, 15"     ← faqat ID'lar matnidagi so'zlar

Bitta pozitsiya bir NECHTA jismoniy qatorga bo'lingan bo'lishi mumkin:
  - Поз. + nom BIRINCHI qatorda, miqdor OXIRGI qatorda (masalan:
    "1 | Радиатор отопительный биметаллический" / "10 секций | шт. | 1")
  - yoki: nom / texnik tavsif (L=, P=, N=, Q= kabi parametrlar, bir
    necha qatorga bo'linishi mumkin) / tip+birlik+miqdor OXIRGI qatorda
  - "1.1)", "1.2)", ">" bilan boshlangan qatorlar — OLDINGI pozitsiyaning
    tarkibi/davomi, YANGI pozitsiya EMAS

Bunday holatlarda barcha jismoniy qatorlarning nom-so'zlari/katak-
ID'larini "naim"ga BIRLASHTIRIB yoz, va HAMMASINI "manba"["naim"]
ro'yxatiga qo'sh (bironta ID'ni tushirib qoldirma — naim'dagi HAR BIR
so'z qaysidir ID'dan kelishi kerak).

  Misol (nom bitta katakda, uning davomi qo'shni katakda —
  "Шаровой кран, DN" ID'si "w5", "15" ID'si "w6"):
  TO'G'RI: "naim": "Шаровой кран, DN 15", "manba": {{"naim": ["w5","w6"]}}

  Misol (tip/ed/kol BOSHQA ID'larga tegishli — ularga TEGMA, faqat
  o'z maydoniga chiqar):
  NOTO'G'RI: "naim": "Тепловентилятор VR MINI (EC) шт. 5", "manba": {{"naim": ["w1","w2","w3","w4"]}}
  TO'G'RI:   "naim": "Тепловентилятор", "tip": "VR MINI (EC)", "ed": "шт.", "kol": "5",
             "manba": {{"naim": ["w1"], "tip": "w2", "ed": "w3", "kol": "w4"}}

"naim" — FAQAT manbadagi XOM matn (ID'lar matnidan yig'ilgan). Hech
qanday o'z izohingni, meta-belgini yoki tushuntirishingni QO'SHMA
(masalan "(davom)", "(davom keyingi sahifada)", "(taxminan)" kabi) —
bunday izoh uchun ALOHIDA "izoh" maydoni bor, undan foydalan.

  NOTO'G'RI: "naim": "Приточно-вытяжная установка. Состав (davom): ... (davom keyingi sahifada)"
  TO'G'RI:   "naim": "Приточно-вытяжная установка. Состав: ...", "izoh": "pozitsiya keyingi sahifada davom etadi"

Nom BILAN tanish emas — quyidagilar pozitsiya EMAS:
  - bo'lim sarlavhasi (faqat nom, miqdorsiz — masalan "Вентиляция",
    "Оборудования для отопления")
  - sahifa sarlavhasi takrori (ustun nomlari — "Поз.", "Наименование...")
  - shtamp maydoni ("Изм.", "Кол.уч.", "Лист", "Инв.№ подл.", imzo maydoni)
  - экспликация помещений (xona/joy ro'yxati — xona nomi + maydon m²,
    masalan "Лестничная клетка 16.4", "Санузел 2.2") — bu ARXITEKTURA
    ma'lumoti, ventilyatsiya/isitish/santexnika USKUNASI EMAS. Bunday
    qatorlarni "otkazib_yuborilgan" ro'yxatiga yoz (sabab kodi:
    "eksplikatsiya"), pozitsiya sifatida BERMA.

═══ MUHIM QOIDALAR — BUZILMASIN ═══

- Agar bitta katak/qatorda IKKI TIL bo'lsa (odatda "/" bilan yoki
  alohida qator bilan ajratilgan rus+ingliz tarjimasi, больница-uslubi
  spetsifikatsiyalarda tez-tez uchraydi) — bu FAQAT "naim"ga tegishli:
  "naim"ga FAQAT RUSCHA qismni yoz, inglizcha tarjimasini TASHLA.
  Masalan "Дымоход, DN / Chimney, DN" -> naim="Дымоход, DN". "manba"["naim"]
  esa BARIBIR o'sha ID'ni (ruscha VA inglizcha qism BIRGA turgan
  bitta so'z/katak bo'lsa ham) ko'rsatsin — tekshiruv "naim"dagi HAR
  BIR (ruscha) so'z shu ID matnida bormi deb tekshiradi, bu ID matnida
  inglizcha qism HAM bo'lishi muammo EMAS.

  Misol: manba katagi (ID "w7") "Циркуляционный насос/Circulation pump, 118 м3/ч"
  TO'G'RI: "naim": "Циркуляционный насос, 118 м3/ч", "manba": {{"naim": ["w7"]}}
- "L=NNN м³/ч" — bu HAVO SARFI (расход воздуха), FIZIK UZUNLIK EMAS.
  Hech qachon uzunlik sifatida talqin qilma.
- "Масса единицы, kg" ustuni — bu OG'IRLIK, miqdor (kol) EMAS. Alohida
  "massa" maydoniga yoz, "kol"ga aralashtirma.
- "kol" (Количество) ustunidagi qiymatni XOM MATN sifatida ber — SON
  SIFATIDA EMAS. Agar u "25/65" kabi ikki qiymatli bo'lsa — aynan
  "25/65" deb yoz, qaysi son kerakligini HAL QILMA (bu boshqa dastur
  qismining vazifasi). Vergul/nuqta, bo'shliq — manbadagidek qoldir.
- Vozduxovod (yoki shunga o'xshash) qatorida ASOSIY "kol" (uzunlik)DAN
  TASHQARI, ALOHIDA katakda ko'pincha yana bitta o'lchov bo'ladi —
  masalan "Всего-1,14 кв.м." yoki "1,14 м2" (jami maydon). Bunday
  katak ko'rinsa — uni "maydon_m2_matn"ga XOM MATN sifatida
  (hisoblamasdan, "Всего"/tire/probelni o'zgartirmasdan) yoz, o'z
  manba-ID'ini "manba"["maydon_m2_matn"]ga qo'sh. Bu — "kol"ni
  ALMASHTIRMAYDI, ikkalasi ham HAQIQIY, mustaqil qiymat (biri
  uzunlik, biri maydon). Bunday katak yo'q bo'lsa — maydonni umuman
  qo'shma (null ham yozmasang bo'ladi).
- HECH NARSANI hisoblama (yig'indi, ko'paytma, birlik o'girish),
  HECH NARSANI tozalama yoki "chiroyli" qilma. Manbada qanday yozilgan
  bo'lsa — xuddi shunday ko'chir (imlo xatosi, qisqartma, katta/kichik
  harf — o'zgarishsiz).
- Bir xil nom bir necha marta takrorlansa (masalan bir nechta bir xil
  radiator, turli seksiya soni bilan) — HAR birini ALOHIDA pozitsiya
  sifatida ber, birlashtirma.

═══ ISHONCHSIZ HOLAT ═══

Agar biror maydonni (tip/ed/kol/prim) ANIQ va ishonchli o'qiy
olmasang — o'sha maydonga null qo'y, "izoh"da sababini qisqacha yoz
(masalan "raqam noaniq, qora dog' bilan qoplangan"). TAXMIN QILMA —
noaniq qiymatdan ko'ra bo'sh maydon yaxshiroq.

"naim" HECH QACHON null bo'lmaydi — bu maydon HAR doim MAJBURIY,
bo'sh bo'lmagan matn. Agar pozitsiyaning nomini (naim) umuman aniq
o'qiy olmasang — bu qatorni "bolimlar"ga QO'SHMA, buning o'rniga
"otkazib_yuborilgan"ga qo'sh: qanday matn ko'rinsa (qisman, noaniq
bo'lsa ham) — xuddi shundayligicha "matn"ga, "sabab" sifatida
"oqilmadi" yoz.

═══ JAVOB FORMATI — ZICH, MAYDON TEJOVCHI (MUHIM, xarajatga ta'sir qiladi) ═══

Javobing FAQAT xom JSON bo'lsin — kirish so'zisiz, izohsiz, markdown
kod blokisiz (```json yozma). Birinchi belgi javobingda darhol "{{"
bo'lishi shart.

JSON ZICH bo'lsin: bo'shliq, chekinish (indentation), yangi qator
ISHLATMA — barcha narsa minimal belgi bilan, quyidagi misoldagidek
bitta qatorda.

Quyidagi maydonlarni FAQAT kerak bo'lganda yoz, aks holda BUTUNLAY
TUSHIRIB QOLDIR (JSON kalitining o'zi ham bo'lmasin):
  - "ishonch": FAQAT "o'rta" yoki "past" bo'lsa yoz. Yozilmasa —
    "yuqori" deb qabul qilinadi (standart holat, aksariyat qatorlar).
  - "izoh": FAQAT aytadigan aniq sabab bo'lsa yoz. Bo'lmasa — umuman
    qo'shma (`null` deb ham yozma, kalitning o'zini tushir).

"manba" maydoni HAR DOIM yoziladi (yuqoridagi ═══ MANBA-ID ═══
bo'limiga qara) — bu maydonlar ichida null bo'lgan qismlarni tushirib
qoldirmasa ham bo'ladi.

"otkazib_yuborilgan"ning "sabab"i — QISQA KOD, erkin matn EMAS,
quyidagi 6 tadan BIRI (boshqa variant yozma):
  "shtamp" | "sarlavha" | "bolim" | "eksplikatsiya" | "oqilmadi" | "boshqa"

Misol (naim/tip/ed/kol/massa/prim MAJBURIY — bo'sh bo'lsa ham
`null` yoz; "poz" ham har doim yoziladi, bo'lmasa `null`; "w4"/"w5"
kabi ID'lar — pastda "KIRISH MA'LUMOTLARI"dagi so'z-ID'lar, MISOL
uchun, haqiqiy so'rovda o'sha so'rovning o'z ID'laridan foydalan):

{{"sahifa":1,"bolimlar":[{{"nom":"Вентиляция / Воздуховоды","qatorlar":[{{"poz":"1","naim":"Радиатор отопительный биметаллический 10 секций","tip":null,"ed":"шт.","kol":"1","massa":null,"prim":null,"manba":{{"naim":["w4","w5"],"ed":"w6","kol":"w7"}}}}]}}],"otkazib_yuborilgan":[{{"matn":"Изм. Кол.уч. Лист № докум. Подп. Дата","sabab":"shtamp"}}]}}

(bu misolda "ishonch"/"izoh" YO'Q — chunki ishonch yuqori va izoh
kerak emas edi; "manba"["naim"] IKKITA ID — chunki bu pozitsiya 2
jismoniy qatorga bo'lingan.)

("sahifa": 1 — bu MISOL uchun, haqiqiy qiymatni pastda "KIRISH
MA'LUMOTLARI"da berilgan aniq sahifa raqamidan ol.)

Agar sahifada hech qanday spetsifikatsiya jadvali topilmasa:
{{"sahifa": <berilgan sahifa raqami>, "bolimlar": [], "otkazib_yuborilgan": []}}"""

# Faza-72, Band 2 (prompt caching, mijoz, 2026-09-12): `_READ_SPEC_PROMPT`
# (yuqorida) HAR so'rovda BAYT-BAYTIGA bir xil — `cache_control:
# ephemeral` bilan belgilanib, `system` parametriga chiqariladi.
# O'ZGARUVCHI qism (sahifa raqami, avvalgi kontekst, so'zlar — bular
# har sahifa/bo'lakda farq qiladi, keshlanSA foyda bermaydi) ALOHIDA,
# `messages`ning o'zida, KESHLANMAGAN holda qoladi. Bu ikki qismga
# bo'lish — 3-bosqichda bitta YAXLIT stringga bog'liq bo'lgan hech
# qanday testni buzmaydi (`ask_claude_read_spec()` chaqiruvchisi
# uchun natija — model javobi — bir xil).
_READ_SPEC_KIRISH_SHABLON = """═══ KIRISH MA'LUMOTLARI ═══

Sahifa raqami: {sahifa_raqami}

Avvalgi sahifadan kontekst (agar bo'lsa — bo'lim/pozitsiya jadval
davom etayotganini bildiradi): {avvalgi_kontekst}

So'zlar (id, matn, x0, y0, x1, y1 — PDF koordinata, chapdan-o'ngga,
yuqoridan-pastga). BIRINCHI ustun — so'z/katakning o'zgarmas ID'si,
"manba" xaritasida AYNAN shu ID'larni ishlat:
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
    system = [
        {
            "type": "text",
            "text": _READ_SPEC_PROMPT.format(),
            "cache_control": {"type": "ephemeral"},
        }
    ]
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
                    "text": _READ_SPEC_KIRISH_SHABLON.format(
                        sahifa_raqami=sahifa_raqami,
                        avvalgi_kontekst=avvalgi_kontekst,
                        sozlar=sozlar_tsv,
                    ),
                },
            ],
        }
    ]
    return _call_anthropic(model=READ_SPEC_MODEL_NAME, messages=messages, max_tokens=max_tokens, system=system)
