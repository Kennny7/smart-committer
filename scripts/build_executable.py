#!/usr/bin/env python3
"""Cross-platform standalone executable builder using PyInstaller."""

import os
import platform
import subprocess
import sys
from pathlib import Path


def main():
    root_dir = Path(__file__).resolve().parent.parent
    os.chdir(root_dir)

    print(f"[INFO] Building standalone executable for platform: {platform.system()} ({platform.machine()})")

    # Ensure pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[INFO] PyInstaller not detected. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0.0"])

    spec_file = root_dir / "smart-committer.spec"
    if not spec_file.exists():
        print(f"[ERROR] Specification file not found: {spec_file}")
        sys.exit(1)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file),
    ]

    print(f"[RUNNING] {' '.join(cmd)}")
    subprocess.check_call(cmd)

    dist_dir = root_dir / "dist"
    binary_name = "smart-committer.exe" if platform.system() == "Windows" else "smart-committer"
    target_path = dist_dir / binary_name

    if target_path.exists():
        size_mb = target_path.stat().st_size / (1024 * 1024)
        print(f"[SUCCESS] Standalone executable generated successfully:")
        print(f"Path: {target_path} ({size_mb:.2f} MB)")
        print(f"Run tests with: {target_path} --help")
    else:
        print(f"[WARN] Build finished but target not found at {target_path}")


if __name__ == "__main__":
    main()
