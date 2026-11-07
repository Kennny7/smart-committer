from smart_committer.models import ChangeType, CommitMode, CommitStyle, FileChange
from smart_committer.git_service import GitService


def test_models_enum():
    assert CommitMode.SINGLE == "single"
    assert CommitMode.ALL == "all"
    assert CommitMode.GROUPED == "grouped"
    assert CommitStyle.CONVENTIONAL == "conventional"


def test_grouping_logic():
    changes = [
        FileChange(path="src/smart_committer/main.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="src/smart_committer/cli.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="docs/guide.md", status="A", change_type=ChangeType.ADDED),
        FileChange(path="README.md", status="M", change_type=ChangeType.MODIFIED),
    ]

    groups = GitService.group_changes(changes)
    scopes = {g.scope for g in groups}
    assert "src/smart_committer" in scopes
    assert "docs" in scopes
    assert "root" in scopes
