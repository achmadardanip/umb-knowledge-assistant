"""LLM-graded RAG metrics — faithfulness + answer-relevance.

Each grader builds a strict JSON-only rubric, calls a chat function (the local Ollama
model in production), and parses the verdict. Pure and unit-testable: the LLM call is
injected via `chat_fn`. Defaults are read from env so thresholds/model are tunable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

GRADER_MODEL = os.getenv("RAG_EVAL_GRADER_MODEL", "qwen2.5:7b-instruct")
FAITHFULNESS_THRESHOLD = float(os.getenv("RAG_EVAL_FAITHFULNESS_THRESHOLD", "0.8"))
RELEVANCE_THRESHOLD = float(os.getenv("RAG_EVAL_RELEVANCE_THRESHOLD", "0.7"))

ChatFn = Callable[[list[dict]], str]


@dataclass
class FaithfulnessVerdict:
    score: float | None
    passed: bool | None
    reason: str
    grader_error: bool = False


@dataclass
class RelevanceVerdict:
    score: float | None
    passed: bool | None
    reason: str
    grader_error: bool = False


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(obj, dict):
        raise ValueError("decoded JSON is not an object")
    return obj


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


_FAITHFULNESS_PROMPT = (
    "You are a strict evaluator. Given a QUESTION, the retrieved CONTEXT, and an ANSWER, "
    "decide whether every factual claim in the ANSWER is supported by the CONTEXT. "
    "Respond with ONLY a JSON object: "
    '{{"score": <0..1 fraction of claims supported>, "supported": [], "unsupported": [], "reason": "<one sentence>"}}.\n\n'
    "QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}\n"
)

_RELEVANCE_PROMPT = (
    "You are a strict evaluator. Given a QUESTION and an ANSWER, rate how directly the "
    "ANSWER addresses the QUESTION (ignore factual correctness, judge relevance only). "
    'Respond with ONLY a JSON object: {{"score": <0..1>, "reason": "<one sentence>"}}.\n\n'
    "QUESTION:\n{question}\n\nANSWER:\n{answer}\n"
)


def grade_faithfulness(question, context, answer, *, chat_fn: ChatFn,
                       threshold: float = FAITHFULNESS_THRESHOLD) -> FaithfulnessVerdict:
    prompt = _FAITHFULNESS_PROMPT.format(question=question, context=context, answer=answer)
    try:
        data = _extract_json(chat_fn([{"role": "user", "content": prompt}]))
        score = _clamp(float(data["score"]))
        return FaithfulnessVerdict(score=score, passed=score >= threshold, reason=str(data.get("reason", "")))
    except Exception as exc:
        return FaithfulnessVerdict(score=None, passed=None, reason=f"grader_error: {exc}", grader_error=True)


def grade_relevance(question, answer, *, chat_fn: ChatFn,
                    threshold: float = RELEVANCE_THRESHOLD) -> RelevanceVerdict:
    prompt = _RELEVANCE_PROMPT.format(question=question, answer=answer)
    try:
        data = _extract_json(chat_fn([{"role": "user", "content": prompt}]))
        score = _clamp(float(data["score"]))
        return RelevanceVerdict(score=score, passed=score >= threshold, reason=str(data.get("reason", "")))
    except Exception as exc:
        return RelevanceVerdict(score=None, passed=None, reason=f"grader_error: {exc}", grader_error=True)


def ollama_chat_fn(temperature: float = 0.0, model: str = GRADER_MODEL) -> ChatFn:
    """Real chat_fn backed by the project's LocalOllamaProvider, using the grader model."""
    from app.llm.local_ollama_provider import LocalOllamaProvider

    provider = LocalOllamaProvider()
    provider.model = model  # honor RAG_EVAL_GRADER_MODEL even if settings.local_llm_model differs

    def _call(messages: list[dict]) -> str:
        return provider.chat(messages, temperature=temperature).content

    return _call
