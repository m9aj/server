#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

# Resolve project path relative to server root
script_dir = Path(os.environ["SCRIPT_DIR"])
project_dir = script_dir.parent / "projects" / "gemma_chat"

if not project_dir.exists():
    print(f"  ERROR: project not found at {project_dir}")
    sys.exit(1)

if not (project_dir / "Containerfile").exists():
    print(f"  ERROR: no Containerfile in {project_dir}")
    sys.exit(1)

# 1. Build local container image
print(f"  Building localhost/gemma-chat:latest from {project_dir}")
result = subprocess.run(
    ["podman", "build", "-t", "localhost/gemma-chat:latest", "."],
    cwd=project_dir,
)
if result.returncode != 0:
    print("  ERROR: podman build failed")
    sys.exit(1)
print("  Build OK")
