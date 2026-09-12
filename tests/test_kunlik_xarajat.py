"""`app/kunlik_xarajat.py` testlari — xotira-asosli holat, HAQIQIY
API'siz. Har test `_holat`ni tozalab boshlaydi (modul-darajasidagi
global, testlar orasida "sizib o'tmasligi" uchun)."""
import app.kunlik_xarajat as kx
from app.kunlik_xarajat import bugungi_xarajat, chegaraga_yetdimi, qoshish, usage_narxi


def setup_function():
    kx._holat["sana"] = None
    kx._holat["jami_dollar"] = 0.0


def test_usage_narxi_hisob_togri():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 500_000}
    assert usage_narxi(usage) == 2.00 + 1.00 + 0.10


def test_usage_narxi_cache_yozish_hisobga_olinadi():
    """Codex/mijoz topgan teshik (2026-09-12): kesh-yozish (birinchi
    so'rov) ILGARI narx-hisobiga UMUMAN kirmasdi."""
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    assert usage_narxi(usage) == 2.50


def test_boshlanishda_nol_xarajat():
    assert bugungi_xarajat() == 0.0
    assert not chegaraga_yetdimi(chegara=2.0)


def test_qoshish_jamlanadi():
    qoshish({"input_tokens": 500_000, "output_tokens": 0, "cache_read_input_tokens": 0})
    assert bugungi_xarajat() == 1.0
    qoshish({"input_tokens": 500_000, "output_tokens": 0, "cache_read_input_tokens": 0})
    assert bugungi_xarajat() == 2.0


def test_chegaraga_yetganda_true():
    qoshish({"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0})
    assert chegaraga_yetdimi(chegara=2.0) is True


def test_eskirgan_sana_qayta_boshlanadi():
    """Kecha yozilgan holat — bugun 0'dan boshlanishi shart (kunlik
    reset)."""
    kx._holat["sana"] = "2000-01-01"
    kx._holat["jami_dollar"] = 99.0
    assert bugungi_xarajat() == 0.0
