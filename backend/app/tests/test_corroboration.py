from app.trust.corroboration import corroboration_count


def test_counts_distinct_authoritative_hosts_with_independent_content():
    contexts = [
        {"hostname": "pmb.mercubuana.ac.id", "authority": 0.8, "chunk_text": "Biaya pendaftaran Rp500.000 untuk semua jalur reguler."},
        {"hostname": "akademik.mercubuana.ac.id", "authority": 0.8, "chunk_text": "Mahasiswa wajib membayar UKT setiap awal semester ganjil baru."},
    ]
    assert corroboration_count(contexts) == 2


def test_mirrored_content_across_hosts_does_not_inflate_corroboration():
    text = "Biaya pendaftaran program sarjana adalah Rp500.000 untuk semua jalur masuk reguler."
    contexts = [
        {"hostname": "pmb.mercubuana.ac.id", "authority": 0.8, "chunk_text": text},
        {"hostname": "mirror.mercubuana.ac.id", "authority": 0.8, "chunk_text": text},
    ]
    assert corroboration_count(contexts) == 1


def test_low_authority_hosts_are_ignored():
    contexts = [
        {"hostname": "pmb.mercubuana.ac.id", "authority": 0.8, "chunk_text": "Biaya pendaftaran Rp500.000 reguler."},
        {"hostname": "klub.mercubuana.ac.id", "authority": 0.3, "chunk_text": "Klub menyatakan biaya yang berbeda sama sekali."},
    ]
    assert corroboration_count(contexts) == 1
