#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

project_dir = Path(os.environ["SCRIPT_DIR"]).parent / "projects" / "Medical Records"

if not project_dir.exists():
    print(f"  ERROR: project not found at {project_dir}")
    sys.exit(1)

if not (project_dir / "Containerfile").exists():
    print(f"  ERROR: no Containerfile in {project_dir}")
    sys.exit(1)

print(f"  Building localhost/medical-records:latest from {project_dir}")
result = subprocess.run(
    ["podman", "build", "-t", "localhost/medical-records:latest", "."],
    cwd=project_dir,
)
if result.returncode != 0:
    print("  ERROR: podman build failed")
    sys.exit(1)

print("  Build OK")
