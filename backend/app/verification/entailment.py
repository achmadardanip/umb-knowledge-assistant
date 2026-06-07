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
