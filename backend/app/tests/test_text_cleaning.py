from app.core.text_cleaning import clean_markdown_text


def test_removes_images():
    assert "http" not in clean_markdown_text("Teks ![foto](https://x.com/a.jpg) lanjut")
    assert clean_markdown_text("![](https://x/p.png)").strip() == ""
    # truncated image fragment (as seen in answers)
    assert "htt" not in clean_markdown_text("Alamat ![](htt")


def test_converts_links_to_text():
    assert clean_markdown_text("Lihat [Situs UMB](https://mercubuana.ac.id)") == "Lihat Situs UMB"
    # broken/truncated link fragment
    out = clean_markdown_text("Kampus Meruya: ](https://mercubuana.ac.id/akademik/program-kelas-reguler#) Jl. Meruya")
    assert "](http" not in out
    assert "Jl. Meruya" in out


def test_strips_headers_and_hashes():
    assert clean_markdown_text("### Program Kelas Reguler ###").strip() == "Program Kelas Reguler"
    assert "#" not in clean_markdown_text("## Judul\nisi")


def test_preserves_plain_text_and_bold_lists():
    src = "Dekan Fasilkom adalah Dr. Budi.\n- Program A\n- Program B"
    out = clean_markdown_text(src)
    assert "Dekan Fasilkom adalah Dr. Budi." in out
    assert "- Program A" in out


def test_handles_empty_and_none():
    assert clean_markdown_text("") == ""
    assert clean_markdown_text(None) == ""
