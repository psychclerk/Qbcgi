#!/usr/bin/env python3
"""Build a standalone qbcgi executable that interprets .qbb at runtime."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build(name: str, onefile: bool = True) -> int:
    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("pyinstaller not found. Install it with: python3 -m pip install pyinstaller", file=sys.stderr)
        return 2

    cmd = [
        pyinstaller,
        "--clean",
        "--noconfirm",
        "--name",
        name,
        "qbcgi.py",
    ]
    if onefile:
        cmd.append("--onefile")

    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd)
    out_dir = Path("dist")
    suffix = ".exe" if sys.platform.startswith("win") else ""
    out_path = out_dir / f"{name}{suffix}"
    print(f"Built runtime executable: {out_path}")
    print(f"Example: {out_path} examples/guestbook.qbb --cgi")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a runtime executable for qbcgi.py")
    ap.add_argument("--name", default="qbcgi", help="Output executable name")
    ap.add_argument("--onedir", action="store_true", help="Build one-dir bundle instead of one-file")
    args = ap.parse_args()
    return build(args.name, onefile=not args.onedir)


if __name__ == "__main__":
    raise SystemExit(main())
