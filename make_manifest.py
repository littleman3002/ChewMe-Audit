#!/usr/bin/env python3
"""Build the NUL-delimited push manifest for chewme-audit.

Excludes build artifacts (build/, *.egg-info, __pycache__, *.pyc) so
they never reach GitHub again. Usage:
    python3 make_manifest.py /tmp/manifest
"""
import os
import sys

SRC = "/home/hatch/workspace/chewme-audit"
EXCLUDE_DIRS = {"__pycache__", "build", ".pytest_cache"}
EXCLUDE_SUFFIXES = (".pyc", ".egg-info")


def excluded(rel):
    parts = rel.split(os.sep)
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if any(p.endswith(".egg-info") for p in parts):
        return True
    if rel.endswith(".pyc"):
        return True
    return False


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/chewme-audit-manifest"
    paths = []
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS
                   and not d.endswith(".egg-info")]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, SRC)
            if excluded(rel):
                continue
            # validate UTF-8
            open(full, "rb").read().decode("utf-8")
            paths.append(rel)
    paths.sort()
    with open(out, "wb") as fh:
        for p in paths:
            fh.write(p.encode("utf-8") + b"\x00")
    print(len(paths), "files ->", out)


if __name__ == "__main__":
    main()
