from smart_committer.models import ChangeType, FileChange
from smart_committer.git_service import GitService


def test_apply_tree_depth_default_unlimited():
    changes = [
        FileChange(path="src/smart_committer/main.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="src/smart_committer/cli.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="tests/test_filter.py", status="A", change_type=ChangeType.ADDED),
        FileChange(path="README.md", status="M", change_type=ChangeType.MODIFIED),
    ]

    # Default depth 0 (unlimited): all 4 files preserved
    res = GitService.apply_tree_depth(changes, tree_depth=0)
    assert len(res) == 4
    paths = [c.path for c in res]
    assert "src/smart_committer/main.py" in paths
    assert "src/smart_committer/cli.py" in paths


def test_apply_tree_depth_level_1():
    changes = [
        FileChange(path="src/smart_committer/main.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="src/smart_committer/cli.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="tests/test_filter.py", status="A", change_type=ChangeType.ADDED),
        FileChange(path="README.md", status="M", change_type=ChangeType.MODIFIED),
    ]

    # Depth 1: src collapsed to 'src', tests collapsed to 'tests', README at root
    res = GitService.apply_tree_depth(changes, tree_depth=1)
    paths = {c.path for c in res}
    assert paths == {"src", "tests", "README.md"}
    assert len(res) == 3


def test_apply_tree_depth_level_2():
    changes = [
        FileChange(path="src/smart_committer/main.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="src/smart_committer/cli.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="src/smart_committer/subpkg/mod.py", status="M", change_type=ChangeType.MODIFIED),
        FileChange(path="README.md", status="M", change_type=ChangeType.MODIFIED),
    ]

    # Depth 2: src/smart_committer collapsed at depth 2
    res = GitService.apply_tree_depth(changes, tree_depth=2)
    paths = {c.path for c in res}
    assert paths == {"src/smart_committer", "README.md"}
