#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve project path relative to server root
script_dir = Path(os.environ["SCRIPT_DIR"])
project_dir = script_dir.parent / "projects" / "resident_lectures"
data_dir = Path(os.environ["DATA_DIR"])

if not project_dir.exists():
    print(f"  ERROR: project not found at {project_dir}")
    sys.exit(1)

if not (project_dir / "Containerfile").exists():
    print(f"  ERROR: no Containerfile in {project_dir}")
    sys.exit(1)

# 1. Build local container image
print(f"  Building localhost/resident-lectures:latest from {project_dir}")
result = subprocess.run(
    ["podman", "build", "-t", "localhost/resident-lectures:latest", "."],
    cwd=project_dir,
)
if result.returncode != 0:
    print("  ERROR: podman build failed")
    sys.exit(1)
print("  Build OK")

# 2. Ensure data volume directory exists on the host
dest_dir = data_dir / "resident-lectures"
if not dest_dir.exists():
    print(f"  Creating data volume directory at {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
else:
    print(f"  Data volume directory already present at {dest_dir}")
