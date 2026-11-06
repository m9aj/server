#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve project path relative to server root
script_dir = Path(os.environ["SCRIPT_DIR"])
apps_dir = Path(os.environ.get("APPS_DIR", Path(os.environ["SCRIPT_DIR"]).parent / "apps"))
project_dir = apps_dir / "census_calc"
data_dir = Path(os.environ["DATA_DIR"])

if not project_dir.exists():
    print(f"  ERROR: project not found at {project_dir}")
    sys.exit(1)

if not (project_dir / "Containerfile").exists():
    print(f"  ERROR: no Containerfile in {project_dir}")
    sys.exit(1)

# 1. Build local container image
print(f"  Building localhost/census-calculator:latest from {project_dir}")
result = subprocess.run(
    ["podman", "build", "-t", "localhost/census-calculator:latest", "."],
    cwd=project_dir,
)
if result.returncode != 0:
    print("  ERROR: podman build failed")
    sys.exit(1)
print("  Build OK")

# 2. Copy Cutoffs.ods to data_dir for runtime volume mounting
dest_dir = data_dir / "census-calculator"
dest_file = dest_dir / "Cutoffs.ods"

if not dest_file.exists():
    print(f"  Initializing data volume at {dest_dir}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    src_file = project_dir / "Cutoffs.ods"
    if src_file.exists():
        shutil.copy2(src_file, dest_file)
        print(f"  Copied default Cutoffs.ods to host data folder")
    else:
        print("  WARNING: Source Cutoffs.ods not found in project directory!")
else:
    print(f"  Cutoffs.ods already present in {dest_dir}")
