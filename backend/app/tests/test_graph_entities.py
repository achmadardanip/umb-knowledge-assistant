from app.graph.entities import extract_entities


def test_extracts_acronym_services():
    ents = extract_entities("Cara aktivasi akun SIA dan SSO untuk mahasiswa baru")
    assert "SIA" in ents and "SSO" in ents


def test_extracts_program_and_faculty_phrases():
    ents = extract_entities("Program studi Teknik Informatika di Fakultas Ilmu Komputer")
    assert "Teknik Informatika" in ents
    assert "Fakultas Ilmu Komputer" in ents


def test_no_spurious_entities_from_generic_lowercase():
    assert extract_entities("berapa biaya kuliah di kampus?") == []


def test_normalizes_and_dedups_case_variants():
    ents = extract_entities("akun sia, SIA, dan Sia bermasalah")
    assert ents.count("SIA") == 1
    assert "SIA" in ents


def test_extracts_scholarship_and_program():
    ents = extract_entities("Beasiswa KIP-K untuk mahasiswa Manajemen")
    assert "KIP-K" in ents
    assert "Manajemen" in ents


def test_unknown_uppercase_acronym_is_captured_but_common_ones_excluded():
    ents = extract_entities("Lihat FAQ dan unduh PDF tentang LPPM kampus")
    assert "LPPM" in ents  # genuine unit acronym
    assert "FAQ" not in ents and "PDF" not in ents  # generic web/file noise
