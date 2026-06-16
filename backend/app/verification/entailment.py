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


class NLIEntailmentChecker:
    """Cross-encoder NLI entailment — the upgrade over ``LexicalEntailmentChecker``
    (which false-flags correct paraphrases). Returns the model's ENTAILMENT
    probability as the support score, so a paraphrase that is genuinely entailed
    scores high without relying on token overlap.

    The transformers model is loaded LAZILY on first use; construction raises
    ``RuntimeError`` if transformers/torch or the weights are unavailable, so the
    factory can fall back. Multilingual by default (handles Indonesian + English).
    """

    DEFAULT_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"

    def __init__(self, model_name: str | None = None) -> None:
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except Exception as exc:  # transformers/torch not installed
            raise RuntimeError(f"NLI checker unavailable: {exc}") from exc
        self._model_name = model_name or self.DEFAULT_MODEL
        self._AutoModel = AutoModelForSequenceClassification
        self._AutoTokenizer = AutoTokenizer
        self._tokenizer = None
        self._model = None
        self._entail_idx: int | None = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        self._tokenizer = self._AutoTokenizer.from_pretrained(self._model_name)
        self._model = self._AutoModel.from_pretrained(self._model_name)
        self._model.eval()
        # Locate the "entailment" class index from the model's label map.
        id2label = {int(k): str(v).lower() for k, v in self._model.config.id2label.items()}
        self._entail_idx = next((i for i, lbl in id2label.items() if "entail" in lbl), 0)

    def entails(self, *, premise: str, hypothesis: str) -> float:
        if not (premise or "").strip() or not (hypothesis or "").strip():
            return 0.0
        try:
            import torch

            self._ensure_loaded()
            inputs = self._tokenizer(
                premise, _MARKER_RE.sub(" ", hypothesis), truncation=True,
                max_length=512, return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**inputs).logits[0]
            probs = torch.softmax(logits, dim=-1)
            return float(probs[self._entail_idx].item())
        except Exception:
            # A model failure must not assert support.
            return 0.0


class MiniCheckEntailmentChecker:
    """MiniCheck grounding checker (preferred when the optional ``minicheck`` package
    is installed). Construction raises ``RuntimeError`` when unavailable so the
    factory falls back to NLI → LLM-judge → lexical."""

    def __init__(self, model_name: str = "flan-t5-large") -> None:
        try:
            from minicheck.minicheck import MiniCheck  # type: ignore
        except Exception as exc:
            raise RuntimeError(f"MiniCheck unavailable: {exc}") from exc
        self._scorer = MiniCheck(model_name=model_name)

    def entails(self, *, premise: str, hypothesis: str) -> float:
        if not (premise or "").strip() or not (hypothesis or "").strip():
            return 0.0
        try:
            _pred, probs, _raw, _ = self._scorer.score(
                docs=[premise], claims=[_MARKER_RE.sub(" ", hypothesis)]
            )
            return float(probs[0])
        except Exception:
            return 0.0
