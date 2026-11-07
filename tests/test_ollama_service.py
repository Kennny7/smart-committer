from smart_committer.models import ChangeType, CommitStyle, FileChange
from smart_committer.ollama_service import OllamaService


def test_ollama_fallback():
    service = OllamaService("test-model", "http://localhost:11434", CommitStyle.CONVENTIONAL)
    change = FileChange(path="src/utils.py", status="M", change_type=ChangeType.MODIFIED)
    msg = service._fallback(change)
    assert msg.startswith("chore: update src/utils.py")

    service_simple = OllamaService("test-model", "http://localhost:11434", CommitStyle.SIMPLE)
    msg_simple = service_simple._fallback(change)
    assert msg_simple.startswith("Update src/utils.py")

    service_gitmoji = OllamaService("test-model", "http://localhost:11434", CommitStyle.GITMOJI)
    msg_gitmoji = service_gitmoji._fallback(change)
    assert msg_gitmoji.startswith("[CHORE] update src/utils.py")


def test_clean_message():
    service = OllamaService("test-model", "http://localhost:11434")
    raw = '```\nfeat(cli): add support for batch commits\n```'
    cleaned = service._clean_message(raw)
    assert cleaned == "feat(cli): add support for batch commits"
