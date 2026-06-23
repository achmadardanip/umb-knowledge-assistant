from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[1] / "promptfooconfig.judges.yaml"

JUDGES = ("qwen7b", "gemma9b", "mistral", "qwen14b")


def test_judges_config_has_per_judge_metrics():
    cfg = yaml.safe_load(CFG.read_text())
    asserts = cfg["defaultTest"]["assert"]
    metrics = {a.get("metric") for a in asserts}
    assert {f"faithfulness_{j}" for j in JUDGES} <= metrics
    assert {f"relevance_{j}" for j in JUDGES} <= metrics


def test_each_assertion_has_own_ollama_grader():
    cfg = yaml.safe_load(CFG.read_text())
    asserts = cfg["defaultTest"]["assert"]
    assert all(str(a.get("provider", "")).startswith("ollama:") for a in asserts)
    providers = {a.get("provider") for a in asserts}
    assert len(providers) >= 4  # at least 4 distinct judge models


def test_faithfulness_uses_context_transform():
    cfg = yaml.safe_load(CFG.read_text())
    faiths = [a for a in cfg["defaultTest"]["assert"] if a["type"] == "context-faithfulness"]
    assert faiths
    assert all(a.get("contextTransform") == "context.metadata.context" for a in faiths)


def test_runs_over_full_scenario_set():
    cfg = yaml.safe_load(CFG.read_text())
    sources = "".join(str(t) for t in cfg["tests"])
    assert "adversarial_scenarios.csv" in sources and "golden_scenarios.csv" in sources
