import logging
from datetime import datetime
from pathlib import Path

_BASE = "smart_committer"


def setup_project_logger(log_dir: Path, project_name: str) -> logging.Logger:
    """Create a per-project, per-day log file. Idempotent."""
    base = logging.getLogger(_BASE)
    base.setLevel(logging.DEBUG)

    for h in list(base.handlers):
        base.removeHandler(h)

    project_log_dir = log_dir / project_name
    project_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = project_log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    base.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    base.addHandler(ch)

    base.info("Logger initialized -> %s", log_file)
    return base


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{_BASE}.{name}")