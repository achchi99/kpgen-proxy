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


def test_model_narxi_sonnet_5_5_tasdiqlangan():
    from app.kunlik_xarajat import model_narxi
    assert model_narxi("claude-sonnet-5-5") == (2.00, 10.00, 0.20, 2.50)


def test_usage_narxi_model_boyicha():
    u = {"model": "claude-haiku-4-5", "input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert usage_narxi(u) == 1.00 + 5.00


def test_noma_lum_model_qimmat_narx_oladi():
    u = {"model": "claude-yangi-noma-lum", "input_tokens": 1_000_000, "output_tokens": 0}
    assert usage_narxi(u) == 15.00
    assert usage_narxi(u) > usage_narxi({"model": "claude-sonnet-5-5", "input_tokens": 1_000_000})


def test_sana_qoshimchali_model_nomi_taniladi():
    from app.kunlik_xarajat import model_narxi
    assert model_narxi("claude-haiku-4-5-20251001") == (1.00, 5.00, 0.10, 1.25)


def test_model_korsatilmasa_standart_narx():
    assert usage_narxi({"input_tokens": 1_000_000}) == 2.00
