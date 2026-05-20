#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

config_path = Path(os.environ["SERVICE_CONFIG"])

if not config_path.exists():
    print(f"  No service config at {config_path}, nothing to do")
    sys.exit(0)

config = yaml.safe_load(config_path.read_text())
models = config.get("models", [])

if not models:
    print("  No models configured")
    sys.exit(0)

# Wait for Ollama to be ready (up to 60s)
print("  Waiting for Ollama to be ready...")
for _ in range(30):
    result = subprocess.run(
        ["podman", "exec", "ollama", "ollama", "list"],
        capture_output=True,
    )
    if result.returncode == 0:
        break
    time.sleep(2)
else:
    print("  ERROR: Ollama did not become ready within 60s")
    sys.exit(1)

# Pull each configured model
for model in models:
    print(f"  Pulling {model} ...")
    result = subprocess.run(["podman", "exec", "ollama", "ollama", "pull", model])
    if result.returncode != 0:
        print(f"  ERROR: failed to pull {model}")
        sys.exit(1)

print("  Models ready")
