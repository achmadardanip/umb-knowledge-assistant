"""Qwen3-Reranker correctness: it must rank the chunk that actually answers the query
above a topically-related but tangential chunk (the exact failure we saw: 'cara daftar'
got answered from an RPL-fees chunk)."""

import pytest

from app.retrieval.reranker import Qwen3Reranker


@pytest.mark.slow
def test_qwen3_ranks_answering_chunk_above_tangential():
    reranker = Qwen3Reranker()
    scores = reranker.score(
        "Bagaimana cara daftar mahasiswa baru di Universitas Mercu Buana?",
        [
            "Cara pendaftaran mahasiswa baru: daftar online melalui PMB UMB, pilih program "
            "studi, unggah dokumen persyaratan, lalu lakukan pembayaran biaya pendaftaran.",
            "Biaya konversi RPL Universitas Mercu Buana untuk lulusan D3 adalah Rp 1.500.000.",
        ],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1], f"answering chunk must outrank tangential one: {scores}"
    assert 0.0 <= scores[0] <= 1.0 and 0.0 <= scores[1] <= 1.0
