"""`app/kunlik_xarajat.py` testlari — disk fayli bilan, HAQIQIY API'siz."""
import json

from app.kunlik_xarajat import bugungi_xarajat, chegaraga_yetdimi, qoshish, usage_narxi


def test_usage_narxi_hisob_togri():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 500_000}
    assert usage_narxi(usage) == 2.00 + 1.00 + 0.10


def test_bosh_fayl_nol_xarajat(tmp_path):
    fayl = tmp_path / "holat.json"
    assert bugungi_xarajat(fayl) == 0.0
    assert not chegaraga_yetdimi(fayl, chegara=2.0)


def test_qoshish_jamlanadi(tmp_path):
    fayl = tmp_path / "holat.json"
    qoshish({"input_tokens": 500_000, "output_tokens": 0, "cache_read_input_tokens": 0}, fayl=fayl)
    assert bugungi_xarajat(fayl) == 1.0
    qoshish({"input_tokens": 500_000, "output_tokens": 0, "cache_read_input_tokens": 0}, fayl=fayl)
    assert bugungi_xarajat(fayl) == 2.0


def test_chegaraga_yetganda_true(tmp_path):
    fayl = tmp_path / "holat.json"
    qoshish({"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 0}, fayl=fayl)
    assert chegaraga_yetdimi(fayl, chegara=2.0) is True


def test_eskirgan_sana_qayta_boshlanadi(tmp_path):
    """Kecha yozilgan holat — bugun 0'dan boshlanishi shart (kunlik
    reset)."""
    fayl = tmp_path / "holat.json"
    fayl.write_text(json.dumps({"sana": "2000-01-01", "jami_dollar": 99.0}), encoding="utf-8")
    assert bugungi_xarajat(fayl) == 0.0
