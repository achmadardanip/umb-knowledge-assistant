"""Generation-quality metrics for the RAG evaluation harness.

These reuse the same claim-extraction and entailment engine as the live CGCV
gate, so "faithfulness" measured offline matches what the gate enforces online.
No heavy evaluation dependency is required; any ``EntailmentChecker`` works
(LLM judge now, MiniCheck/NLI later).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.verification.claim_gate import premise_for
from app.verification.claims import extract_claims
from app.verification.entailment import EntailmentChecker


def faithfulness_score(
    answer: str,
    contexts_by_citation: dict[int, dict],
    checker: EntailmentChecker,
    *,
    threshold: float = 0.5,
) -> float:
    """Fraction of atomic claims entailed by their cited evidence.

    An answer with no factual claims (e.g. an abstention) scores 1.0 — it
    asserts nothing false. Uncited claims are counted as unfaithful.
    """
    claims = extract_claims(answer)
    if not claims:
        return 1.0
    supported = 0
    for claim in claims:
        premise = premise_for(claim, contexts_by_citation)
        if claim.citation_ids and premise and checker.entails(premise=premise, hypothesis=claim.text) >= threshold:
            supported += 1
    return supported / len(claims)


@dataclass
class CitationMetrics:
    precision: float  # of the claims that cite a source, fraction actually supported
    recall: float  # of all claims, fraction supported by an entailing citation


def citation_metrics(
    answer: str,
    contexts_by_citation: dict[int, dict],
    checker: EntailmentChecker,
    *,
    threshold: float = 0.5,
) -> CitationMetrics:
    """ALCE-style citation precision/recall at the atomic-claim level."""
    claims = extract_claims(answer)
    if not claims:
        return CitationMetrics(precision=1.0, recall=1.0)
    cited = 0
    supported = 0
    for claim in claims:
        if not claim.citation_ids:
            continue
        cited += 1
        premise = premise_for(claim, contexts_by_citation)
        if premise and checker.entails(premise=premise, hypothesis=claim.text) >= threshold:
            supported += 1
    precision = supported / cited if cited else 1.0
    recall = supported / len(claims)
    return CitationMetrics(precision=precision, recall=recall)


def abstention_outcome(*, predicted_not_found: bool, expected_not_found: bool) -> str:
    """Classify an abstention decision against the gold label.

    ``missed_abstention`` is the dangerous quadrant (answered when it should
    have abstained); ``over_abstention`` is the usability cost (abstained when
    an official answer existed).
    """
    if expected_not_found:
        return "correct_abstention" if predicted_not_found else "missed_abstention"
    return "over_abstention" if predicted_not_found else "answered"


@dataclass
class RiskCoverage:
    threshold: float
    coverage: float  # fraction of claims admitted (score >= threshold)
    risk: float  # fraction of admitted claims that are not truly supported


def risk_coverage_points(
    records: list[tuple[float, bool]],
    thresholds: list[float],
) -> list[RiskCoverage]:
    """Risk–coverage curve over admission thresholds.

    ``records`` are ``(support_score, is_truly_supported)`` pairs. Used to pick
    the C²GV admission threshold that trades coverage for a target risk level.
    """
    total = len(records)
    points: list[RiskCoverage] = []
    for threshold in thresholds:
        admitted = [is_supported for score, is_supported in records if score >= threshold]
        coverage = len(admitted) / total if total else 0.0
        risk = sum(1 for is_supported in admitted if not is_supported) / len(admitted) if admitted else 0.0
        points.append(RiskCoverage(threshold=threshold, coverage=coverage, risk=risk))
    return points


def calibrate_threshold(
    records: list[tuple[float, bool]],
    *,
    target_risk: float,
    thresholds: list[float],
) -> float:
    """Lowest threshold (i.e. maximum coverage) whose empirical risk <= target.

    This is the empirical selector; the distribution-free conformal correction
    (Learn-then-Test finite-sample bound) is layered on in the C²GV workstream.
    """
    for threshold in sorted(thresholds):
        admitted = [is_supported for score, is_supported in records if score >= threshold]
        if not admitted:
            continue
        risk = sum(1 for is_supported in admitted if not is_supported) / len(admitted)
        if risk <= target_risk:
            return threshold
    return max(thresholds)


def _risk_upper_bound(errors: int, n: int, confidence: float) -> float:
    """One-sided Hoeffding upper confidence bound on the risk of a 0/1 loss."""
    if n == 0:
        return 1.0
    empirical = errors / n
    return empirical + math.sqrt(math.log(1.0 / confidence) / (2 * n))


def conformal_threshold(
    records: list[tuple[float, bool]],
    *,
    target_risk: float,
    confidence: float,
    thresholds: list[float],
    min_admitted: int = 1,
) -> float:
    """Distribution-free admission threshold for C²GV (Learn-then-Test style).

    Returns the lowest threshold (maximum coverage) whose risk *upper confidence
    bound* is <= ``target_risk`` at level ``confidence`` — so the probability of
    asserting an unsupported claim is provably bounded, accounting for finite
    calibration data. When no threshold can be certified, returns the maximum
    threshold (abstain-all), the safe default. The Hoeffding bound here can be
    swapped for a tighter Hoeffding–Bentkus bound without changing callers.
    """
    for threshold in sorted(thresholds):
        admitted = [is_supported for score, is_supported in records if score >= threshold]
        if len(admitted) < min_admitted:
            continue
        errors = sum(1 for is_supported in admitted if not is_supported)
        if _risk_upper_bound(errors, len(admitted), confidence) <= target_risk:
            return threshold
    return max(thresholds)
