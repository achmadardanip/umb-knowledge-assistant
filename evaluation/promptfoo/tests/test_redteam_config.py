from pathlib import Path

import yaml

CFG = Path(__file__).resolve().parents[1] / "promptfooconfig.redteam.yaml"


def test_redteam_targets_the_chatbot():
    cfg = yaml.safe_load(CFG.read_text())
    providers = cfg.get("providers") or cfg.get("targets")
    assert providers and providers[0]["id"] == "file://rag_chat_provider.py"


def test_redteam_uses_attack_scenarios():
    cfg = yaml.safe_load(CFG.read_text())
    sources = "".join(str(t) for t in cfg["tests"])
    assert "redteam_scenarios.csv" in sources


def test_redteam_has_local_resistance_rubric():
    cfg = yaml.safe_load(CFG.read_text())
    asserts = cfg["defaultTest"]["assert"]
    assert any(a["type"] == "llm-rubric" for a in asserts)
    assert {a.get("metric") for a in asserts} >= {"attack_resisted"}
    assert cfg["defaultTest"]["options"]["provider"].startswith("ollama:")
