"""kpgen VPS proxy — FastAPI ilova.

Vazifasi: kpgen desktop dasturidan kelgan so'rovlarni Anthropic API'ga
yo'naltiradi (API kalit faqat shu serverda, kodda emas — CLAUDE.md §6).
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.anthropic_client import ProxyError, ask_claude

app = FastAPI(title="kpgen-proxy")


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Server hech qachon qulamasin — kutilmagan har qanday xato ham
    tushunarli JSON bo'lib qaytadi."""
    return JSONResponse(status_code=500, content={"error": f"Kutilmagan server xatosi: {exc}"})


class ClassifyRequest(BaseModel):
    text: str = Field(min_length=1)


class ClassifyResponse(BaseModel):
    category: str


_CLASSIFY_PROMPT = (
    "Sen ventilyatsiya jihozlari nomlarini tasniflaydigan yordamchisan. "
    "Quyidagi nomga eng mos keladigan qisqa kategoriya nomini rus tilida, "
    "boshqa hech qanday izohsiz, faqat kategoriya nomining o'zini qaytar:\n\n"
    "{text}"
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/classify", response_model=ClassifyResponse)
def classify(payload: ClassifyRequest):
    try:
        category = ask_claude(_CLASSIFY_PROMPT.format(text=payload.text))
    except ProxyError as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    return ClassifyResponse(category=category)
