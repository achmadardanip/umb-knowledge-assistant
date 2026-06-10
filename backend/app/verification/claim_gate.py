"""Corroboration-Gated Claim Verification (CGCV) — the trust gate.

Each atomic claim is verified by entailment against the chunk(s) it cites.
Claims that are uncited, cite an unknown source, or are not entailed are
dropped. If too few claims survive, the system abstains rather than assert.
This replaces the previous behaviour where any sentence could be auto-stapled
with a ``[1]`` citation regardless of support (a hallucination / false-citation
vector, and an indirect-prompt-injection vector — injected instructions are not
entailed by legitimate evidence).

The conformal calibration layer (C²GV) will later set ``threshold`` from a
labelled calibration set to bound the asserted-but-unsupported rate; for now it
is a conservative fixed default.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.citation_validator import FALLBACK_ANSWER
from app.verification.claims import Claim, extract_claims
from app.verification.entailment import EntailmentChecker


@dataclass
class GateResult:
    answer: str
    supported_claims: list[Claim]
    dropped_claims: list[Claim]
    not_found: bool
    confidence: str


def premise_for(claim: Claim, contexts_by_citation: dict[int, dict]) -> str:
    parts: list[str] = []
    for citation_id in claim.citation_ids:
        context = contexts_by_citation.get(citation_id)
        if not context:
            continue
        chunk_text = (context.get("chunk_text") or "").strip()
        if chunk_text:
            parts.append(chunk_text)
    return "\n\n".join(parts)


def _render_claim(claim: Claim) -> str:
    markers = "".join(f"[{citation_id}]" for citation_id in claim.citation_ids)
    text = claim.text.rstrip()
    if not markers:
        return text
    if text and text[-1] in ".!?":
        return f"{text[:-1].rstrip()} {markers}{text[-1]}"
    return f"{text} {markers}"


def verify_claims(
    answer: str,
    contexts_by_citation: dict[int, dict],
    checker: EntailmentChecker,
    *,
    threshold: float = 0.5,
    min_supported: int = 1,
) -> GateResult:
    claims = extract_claims(answer)
    supported: list[Claim] = []
    dropped: list[Claim] = []
    for claim in claims:
        premise = premise_for(claim, contexts_by_citation)
        if not claim.citation_ids or not premise:
            dropped.append(claim)
            continue
        score = checker.entails(premise=premise, hypothesis=claim.text)
        if score >= threshold:
            supported.append(claim)
        else:
            dropped.append(claim)

    if len(supported) < min_supported:
        return GateResult(
            answer=FALLBACK_ANSWER,
            supported_claims=[],
            dropped_claims=claims,
            not_found=True,
            confidence="low",
        )

    rendered = " ".join(_render_claim(claim) for claim in supported).strip()
    return GateResult(
        answer=rendered,
        supported_claims=supported,
        dropped_claims=dropped,
        not_found=False,
        confidence="high" if not dropped else "medium",
    )
