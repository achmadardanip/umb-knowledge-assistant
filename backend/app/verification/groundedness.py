"""
P4 — answer-level groundedness verification + decision.

Sits on top of the same claim-extraction + entailment engine as the live CGCV
gate (``verify_claims``), but produces an explicit answer-level *groundedness
score* and a *decision* (return / regenerate / abstain) per the Phase-6 thresholds:

    score >= return_threshold (0.90)        -> return
    regenerate_threshold (0.70) <= score    -> regenerate once
    score <  regenerate_threshold           -> abstain (official sources only)

The entailment engine is pluggable and degrades gracefully:
MiniCheck -> NLI -> LLM-judge -> Lexical (whichever is available), so the
paraphrase-false-flagging lexical checker is only the last resort.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.verification.claim_gate import premise_for
from app.verification.claims import extract_claims
from app.verification.entailment import (
    ChatFn,
    EntailmentChecker,
    LexicalEntailmentChecker,
    LLMJudgeEntailmentChecker,
)

logger = logging.getLogger(__name__)

DECISION_RETURN = "return"
DECISION_REGENERATE = "regenerate"
DECISION_ABSTAIN = "abstain"


@dataclass
class GroundednessResult:
    score: float                  # supported claims / total claims (1.0 if no claims)
    supported: int
    total: int
    unsupported_claim_rate: float
    citation_alignment: float     # fraction of claims whose [n] all map to retrieved contexts
    decision: str
    checker: str


def _citation_alignment(claims, contexts_by_citation: dict[int, dict]) -> float:
    """Structural alignment (no LLM): fraction of cited claims whose every [n] marker
    points to an actually-retrieved context. Catches fabricated/dangling citations."""
    cited = [c for c in claims if c.citation_ids]
    if not cited:
        return 1.0
    aligned = sum(
        1 for c in cited if all(cid in contexts_by_citation for cid in c.citation_ids)
    )
    return aligned / len(cited)


def build_groundedness_checker(
    preference: str = "auto",
    *,
    chat: ChatFn | None = None,
) -> tuple[EntailmentChecker, str]:
    """Construct the best available entailment checker. Order for ``auto``:
    MiniCheck -> NLI -> LLM-judge (if ``chat``) -> Lexical. A specific preference
    is attempted first, then falls through the same chain. Never raises."""
    pref = (preference or "auto").lower()

    def _minicheck():
        from app.verification.entailment import MiniCheckEntailmentChecker
        return MiniCheckEntailmentChecker(), "minicheck"

    def _nli():
        from app.verification.entailment import NLIEntailmentChecker
        return NLIEntailmentChecker(), "nli"

    def _llm():
        if chat is None:
            raise RuntimeError("no chat fn for llm judge")
        return LLMJudgeEntailmentChecker(chat=chat), "llm"

    def _lexical():
        return LexicalEntailmentChecker(), "lexical"

    builders = {"minicheck": _minicheck, "nli": _nli, "llm": _llm, "lexical": _lexical}
    if pref == "auto":
        order = ["minicheck", "nli", "llm", "lexical"]
    else:
        order = [pref] + [b for b in ["minicheck", "nli", "llm", "lexical"] if b != pref]

    for name in order:
        builder = builders.get(name)
        if builder is None:
            continue
        try:
            return builder()
        except Exception as exc:  # unavailable engine → try the next
            logger.info("groundedness checker '%s' unavailable: %s", name, exc)
    return LexicalEntailmentChecker(), "lexical"


class GroundednessVerifier:
    """Scores an answer against its cited evidence and recommends a decision."""

    def __init__(
        self,
        checker: EntailmentChecker,
        *,
        checker_name: str = "lexical",
        claim_threshold: float = 0.5,
        return_threshold: float = 0.90,
        regenerate_threshold: float = 0.70,
    ) -> None:
        self._checker = checker
        self._name = checker_name
        self._claim_threshold = claim_threshold
        self._return_threshold = return_threshold
        self._regenerate_threshold = regenerate_threshold

    def _decide(self, score: float) -> str:
        if score >= self._return_threshold:
            return DECISION_RETURN
        if score >= self._regenerate_threshold:
            return DECISION_REGENERATE
        return DECISION_ABSTAIN

    def verify(self, answer: str, contexts_by_citation: dict[int, dict]) -> GroundednessResult:
        claims = extract_claims(answer or "")
        total = len(claims)
        if total == 0:
            # An answer asserting no factual claims (e.g. a clean abstention) is
            # vacuously grounded — it cannot hallucinate a fact.
            return GroundednessResult(
                score=1.0, supported=0, total=0, unsupported_claim_rate=0.0,
                citation_alignment=1.0, decision=DECISION_RETURN, checker=self._name,
            )
        supported = 0
        for claim in claims:
            premise = premise_for(claim, contexts_by_citation)
            if claim.citation_ids and premise and self._checker.entails(
                premise=premise, hypothesis=claim.text
            ) >= self._claim_threshold:
                supported += 1
        score = supported / total
        return GroundednessResult(
            score=score,
            supported=supported,
            total=total,
            unsupported_claim_rate=1.0 - score,
            citation_alignment=_citation_alignment(claims, contexts_by_citation),
            decision=self._decide(score),
            checker=self._name,
        )
