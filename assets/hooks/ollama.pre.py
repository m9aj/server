#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

# Install nvidia-container-toolkit if missing
if subprocess.run(["which", "nvidia-ctk"], capture_output=True).returncode != 0:
    print("  Installing nvidia-container-toolkit...")
    result = subprocess.run(["sudo", "pacman", "-S", "nvidia-container-toolkit", "--needed", "--noconfirm"])
    if result.returncode != 0:
        print("  ERROR: failed to install nvidia-container-toolkit")
        sys.exit(1)

# Generate CDI spec if missing
if not Path("/etc/cdi/nvidia.yaml").exists():
    print("  Generating CDI spec...")
    result = subprocess.run(["sudo", "nvidia-ctk", "cdi", "generate", "--output=/etc/cdi/nvidia.yaml"])
    if result.returncode != 0:
        print("  ERROR: failed to generate CDI spec")
        sys.exit(1)

# Ensure data dir exists
data_dir = Path(os.environ["DATA_DIR"]) / "ollama"
data_dir.mkdir(parents=True, exist_ok=True)
print(f"  Data dir: {data_dir}")
print("  Pre-flight OK")
