import pytest
from smart_committer.file_filter import FileFilter


def test_default_ignores():
    ff = FileFilter()
    assert not ff.is_allowed(".venv/bin/python")
    assert not ff.is_allowed("node_modules/package.json")
    assert not ff.is_allowed(".git/config")  # .git is ignored or git handled
    assert not ff.is_allowed("app.db")
    assert not ff.is_allowed("src/__pycache__/module.pyc")
    assert not ff.is_allowed(".env")
    assert ff.is_allowed(".env.example")
    assert ff.is_allowed("src/main.py")
    assert ff.is_allowed("README.md")


def test_explicit_exclude():
    ff = FileFilter(excludes=["*.md", "docs/*"])
    assert not ff.is_allowed("README.md")
    assert not ff.is_allowed("docs/guide.html")
    assert ff.is_allowed("src/smart_committer/main.py")


def test_explicit_include():
    ff = FileFilter(includes=["src/**/*.py"])
    assert ff.is_allowed("src/smart_committer/main.py")
    assert not ff.is_allowed("package.json")
    assert not ff.is_allowed("docs/index.md")


def test_force_include_overrides_default():
    ff = FileFilter(force_includes=[".env"])
    assert ff.is_allowed(".env")
