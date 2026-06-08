"""Cross-Lingual Entailment Consistency (XLEC) — a multilingual trust feature.

A claim may be in a different language than the source it cites (an English
question answered from an Indonesian page, or vice versa). Translation can
introduce drift, so a claim entailed across languages carries more risk than a
same-language one. XLEC flags cross-lingual claims and contributes a penalty to
the C²GV support score, raising the admission bar for them.
"""

from __future__ import annotations

from app.rag.language import detect_language


def is_cross_lingual(claim: str, chunk: str) -> bool:
    claim_lang = detect_language(claim)
    chunk_lang = detect_language(chunk)
    if "auto" in (claim_lang, chunk_lang):
        return False  # undetermined language -> do not flag
    return claim_lang != chunk_lang


def xlec_penalty(claim: str, chunk: str, *, penalty: float = 0.2) -> float:
    """A support-score penalty for translation-drift risk on cross-lingual claims."""
    return penalty if is_cross_lingual(claim, chunk) else 0.0
