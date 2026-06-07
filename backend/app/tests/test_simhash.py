from app.trust.simhash import hamming_distance, is_near_duplicate, simhash


def test_hamming_distance_counts_differing_bits():
    assert hamming_distance(0b1010, 0b1000) == 1
    assert hamming_distance(0b1111, 0b0000) == 4


def test_identical_text_has_zero_distance():
    text = "Biaya pendaftaran program sarjana adalah Rp500.000 untuk semua jalur masuk."
    assert simhash(text) == simhash(text)
    assert is_near_duplicate(text, text)


def test_minor_edit_is_near_duplicate():
    a = "Biaya pendaftaran program sarjana adalah Rp500.000 untuk semua jalur masuk reguler."
    b = "Biaya pendaftaran program sarjana adalah Rp500.000 untuk seluruh jalur masuk reguler."
    assert is_near_duplicate(a, b)


def test_unrelated_text_is_not_near_duplicate():
    a = "Biaya pendaftaran program sarjana adalah Rp500.000 untuk semua jalur masuk reguler."
    b = "Perpustakaan pusat universitas buka setiap hari kerja mulai pukul delapan pagi."
    assert not is_near_duplicate(a, b)
