"""Entailment checking for claim verification.

An :class:`EntailmentChecker` answers: *does this premise (cited chunk) support
this hypothesis (atomic claim)?* The production engine is MiniCheck/NLI served
through the model gateway; today we ship a provider-backed LLM judge. The gate
depends only on the protocol, so the engine is swappable (managed now,
self-hosted later) without touching gate logic.
"""

from __future__ import annotations

import re
from typing import Callable, Protocol, runtime_checkable

_YES = re.compile(r"\byes\b", re.IGNORECASE)
_NO = re.compile(r"\bno\b", re.IGNORECASE)

ChatFn = Callable[[list[dict]], str]


@runtime_checkable
class EntailmentChecker(Protocol):
    def entails(self, *, premise: str, hypothesis: str) -> float:
        """Return an entailment score in ``[0, 1]`` (1 = premise supports hypothesis)."""
        ...


_WORD_RE = re.compile(r"[a-z]{3,}")
_NUM_RE = re.compile(r"\d[\d.,]*\d|\d")
_MARKER_RE = re.compile(r"\[\d+\]")
_OVERLAP_FLOOR = 0.3
_STOPWORDS = frozenset({
    "adalah", "untuk", "dan", "yang", "pada", "dengan", "atau", "ini", "itu", "dari",
    "dapat", "akan", "oleh", "juga", "agar", "bisa", "harus", "tidak", "ada", "dalam",
    "sebagai", "serta", "kepada", "para", "telah", "sudah", "saat", "melalui", "secara",
    "the", "and", "for", "with", "are", "was", "were", "can", "will", "via", "through",
})


class LexicalEntailmentChecker:
    """Free, offline entailment proxy — no LLM call, so CGCV can run on every answer
    without consuming rate-limited quota.

    Two signals: (1) numeric consistency — any number in the claim that is absent from
    the cited chunk marks it fabricated (the worst hallucination: wrong fees/dates);
    (2) salient-token overlap between claim and chunk. A plausible procedure cited to
    an unrelated chunk has near-zero overlap and is dropped; a paraphrase of a genuinely
    supported fact keeps enough overlap to pass.
    """

    def entails(self, *, premise: str, hypothesis: str) -> float:
        prem = (premise or "").lower()
        hyp = _MARKER_RE.sub(" ", (hypothesis or "").lower())
        if not prem.strip() or not hyp.strip():
            return 0.0
        # Numeric consistency: a hypothesis number not present in the premise is fabricated.
        hyp_numbers = {n for n in _NUM_RE.findall(hyp) if len(n) >= 2}
        if any(number not in prem for number in hyp_numbers):
            return 0.2
        prem_words = set(_WORD_RE.findall(prem))
        salient = {word for word in _WORD_RE.findall(hyp) if word not in _STOPWORDS}
        if not salient:
            return 1.0  # contentless claim whose numbers (if any) already verified
        overlap = sum(1 for word in salient if word in prem_words) / len(salient)
        if overlap >= _OVERLAP_FLOOR:
            return min(1.0, 0.6 + 0.4 * overlap)
        return overlap


class LLMJudgeEntailmentChecker:
    """Entailment via a strict YES/NO LLM judgement.

    ``chat`` is injected (a function taking chat messages and returning the
    assistant text) so this is unit-testable without network access and works
    with any configured provider.
    """

    def __init__(self, chat: ChatFn) -> None:
        self._chat = chat

    def entails(self, *, premise: str, hypothesis: str) -> float:
        prompt = (
            "You are a strict factual entailment checker. Decide whether the PREMISE "
            "fully supports the HYPOTHESIS. Reply with exactly one word: YES or NO.\n\n"
            f"PREMISE:\n{premise}\n\nHYPOTHESIS:\n{hypothesis}"
        )
        try:
            content = (self._chat([{"role": "user", "content": prompt}]) or "").strip()
        except Exception:
            # Conservative: an unavailable judge must not assert support.
            return 0.0
        has_no = bool(_NO.search(content))
        has_yes = bool(_YES.search(content))
        if has_yes and not has_no:
            return 1.0
        # Anything else (NO, ambiguous, or empty) is treated as not entailed.
        return 0.0
