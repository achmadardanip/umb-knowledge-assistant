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
