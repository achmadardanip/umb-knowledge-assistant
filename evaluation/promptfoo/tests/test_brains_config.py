from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[1] / "promptfooconfig.brains.yaml"

EXPECTED_BRAINS = {"qwen2.5:7b-instruct", "llama3.2:3b", "gemma2:9b", "mistral:7b", "qwen2.5:14b"}


def test_brains_are_distinct_answer_model_columns():
    cfg = yaml.safe_load(CFG.read_text())
    providers = cfg["providers"]
    assert len(providers) >= 5
    assert all(p["id"] == "file://rag_chat_provider.py" for p in providers)
    brains = {p["config"]["answer_model"] for p in providers}
    assert EXPECTED_BRAINS <= brains
    # all compare under the same retrieval mode so only the brain varies
    assert {p["config"]["retrieval_mode"] for p in providers} == {"hybrid"}


def test_single_grader_and_named_metrics():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["defaultTest"]["options"]["provider"].startswith("ollama:")
    metrics = {a.get("metric") for a in cfg["defaultTest"]["assert"]}
    assert {"faithfulness", "relevance", "official_source"} <= metrics


def test_runs_over_full_scenario_set():
    cfg = yaml.safe_load(CFG.read_text())
    sources = "".join(str(t) for t in cfg["tests"])
    assert "adversarial_scenarios.csv" in sources and "golden_scenarios.csv" in sources
