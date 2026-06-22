from pathlib import Path
import yaml

CFG = Path(__file__).resolve().parents[1] / "promptfooconfig.monitoring.yaml"


def test_config_is_valid_yaml_with_required_keys():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["providers"][0]["id"] == "file://rag_chat_provider.py"
    assert cfg["defaultTest"]["options"]["provider"].startswith("ollama:")
    types = [a["type"] for a in cfg["defaultTest"]["assert"]]
    assert "context-faithfulness" in types
    assert "llm-rubric" in types
    assert "scenarios.csv" in "".join(str(t) for t in cfg["tests"])


def test_named_metrics_present():
    cfg = yaml.safe_load(CFG.read_text())
    metrics = {a.get("metric") for a in cfg["defaultTest"]["assert"]}
    assert {"faithfulness", "relevance", "official_source"} <= metrics


def test_two_provider_columns_for_charts():
    # Charts need >=2 comparison columns; we compare retrieval modes on the same endpoint.
    cfg = yaml.safe_load(CFG.read_text())
    modes = {p["config"]["retrieval_mode"] for p in cfg["providers"]}
    assert modes == {"indexed", "hybrid"}
    assert all(p["id"] == "file://rag_chat_provider.py" for p in cfg["providers"])
