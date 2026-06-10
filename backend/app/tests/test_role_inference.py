from app.chat.role_inference import infer_audience


def test_infers_calon_mahasiswa():
    assert infer_audience("Saya calon mahasiswa, bagaimana cara daftar?") == "calon_mahasiswa"


def test_infers_orang_tua_over_calon():
    assert infer_audience("anak saya mau daftar kuliah di UMB") == "orang_tua"


def test_infers_mahasiswa_from_krs():
    assert infer_audience("KRS saya error, gimana memperbaikinya?") == "mahasiswa"


def test_infers_alumni():
    assert infer_audience("cara legalisir ijazah saya sebagai alumni") == "alumni"


def test_infers_dosen():
    assert infer_audience("saya dosen, bagaimana akses sistem akademik?") == "dosen"


def test_returns_none_for_general_public():
    assert infer_audience("Berapa biaya kuliah di UMB?") is None
