#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve project path relative to server root
script_dir = Path(os.environ["SCRIPT_DIR"])
project_dir = script_dir.parent / "projects" / "resident_schedule"
data_dir = Path(os.environ["DATA_DIR"])

if not project_dir.exists():
    print(f"  ERROR: project not found at {project_dir}")
    sys.exit(1)

if not (project_dir / "Containerfile").exists():
    print(f"  ERROR: no Containerfile in {project_dir}")
    sys.exit(1)

# 1. Build local container image
print(f"  Building localhost/resident-schedule:latest from {project_dir}")
result = subprocess.run(
    ["podman", "build", "-t", "localhost/resident-schedule:latest", "."],
    cwd=project_dir,
)
if result.returncode != 0:
    print("  ERROR: podman build failed")
    sys.exit(1)
print("  Build OK")

# 2. Copy schedule.ods to data_dir for runtime volume mounting
dest_dir = data_dir / "resident-schedule"
dest_file = dest_dir / "schedule.ods"

if not dest_file.exists():
    print(f"  Initializing data volume at {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_file = project_dir / "schedule.ods"
    if src_file.exists():
        shutil.copy2(src_file, dest_file)
        print(f"  Copied default schedule.ods to host data folder")
    else:
        print("  WARNING: Source schedule.ods not found in project directory!")
else:
    print(f"  schedule.ods already present in {dest_dir}")
