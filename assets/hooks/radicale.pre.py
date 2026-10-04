#!/usr/bin/env python3
import os
import sys
import json
import subprocess
from pathlib import Path
import yaml

data_dir = Path(os.environ.get("DATA_DIR", "/mnt/containers/data"))
script_dir = Path(os.environ.get("SCRIPT_DIR", Path(__file__).parent.parent))

radicale_dir = data_dir / "radicale"
config_dir = radicale_dir / "config"
collections_dir = radicale_dir / "collections"

config_dir.mkdir(parents=True, exist_ok=True)
collections_dir.mkdir(parents=True, exist_ok=True)

# 1. Ensure config file exists
config_file = config_dir / "config"
if not config_file.exists():
    print(f"  Creating default Radicale config at {config_file}...")
    config_content = """[server]
script_name = /caldav
hosts = 0.0.0.0:5232
max_connections = 20
max_content_length = 100000000

[storage]
filesystem_folder = /var/lib/radicale/collections

[auth]
type = htpasswd
htpasswd_filename = /etc/radicale/users
htpasswd_encryption = bcrypt

[rights]
type = from_file
file = /etc/radicale/rights

[web]
type = internal

[logging]
level = info
"""
    config_file.write_text(config_content)

# 2. Ensure rights file exists
rights_file = config_dir / "rights"
if not rights_file.exists():
    print(f"  Creating default Radicale rights file at {rights_file}...")
    rights_content = """# Allow authenticated users to read root for CalDAV discovery
[root]
user = .+
collection = 
permissions = R

# Allow authenticated users full read/write to their own collections
[owner-write]
user = .+
collection = {user}(/.*)?
permissions = RrWw

# Allow read access for public / shared collections (.ics subscriptions)
[public-read]
user = .*
collection = .*/public(\\.ics|/.*)?
permissions = Rr
"""
    rights_file.write_text(rights_content)

# 3. Read credentials from secrets
def get_secret(key):
    plain_path = script_dir / "config" / "secrets.yaml"
    if plain_path.exists():
        try:
            with open(plain_path) as f:
                data = yaml.safe_load(f)
                if data and "secrets" in data and key in data["secrets"]:
                    return str(data["secrets"][key])
        except Exception:
            pass

    age_path = script_dir / "config" / "secrets.yaml.age"
    if age_path.exists():
        try:
            res = subprocess.run(["age", "--decrypt", str(age_path)], capture_output=True, text=True)
            if res.returncode == 0:
                data = yaml.safe_load(res.stdout)
                if data and "secrets" in data and key in data["secrets"]:
                    return str(data["secrets"][key])
        except Exception:
            pass

    try:
        res = subprocess.run(["podman", "secret", "inspect", "--showsecret", key], capture_output=True, text=True)
        if res.returncode == 0:
            return json.loads(res.stdout)[0]["SecretData"]
    except Exception:
        pass

    return None

username = get_secret("radicale_user") or "m9ajay"
password = get_secret("radicale_password")

users_file = config_dir / "users"
if not users_file.exists() or not users_file.read_text().strip():
    if not password:
        print("  ERROR: No radicale_password found in secrets.yaml or podman secret store")
        sys.exit(1)

    print(f"  Generating htpasswd entry for user '{username}' from secrets...")
    cmd = [
        "podman", "run", "--rm", "-i",
        "--entrypoint", "/app/bin/python",
        "ghcr.io/kozea/radicale:stable",
        "-c",
        "import sys; from passlib.hash import bcrypt; u, p = sys.stdin.read().splitlines()[:2]; print(f'{u}:{bcrypt.hash(p)}')\n"
    ]
    res = subprocess.run(cmd, input=f"{username}\n{password}\n", capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        subprocess.run(["podman", "unshare", "tee", str(users_file)], input=res.stdout, text=True, check=True, stdout=subprocess.DEVNULL)
        print(f"  Successfully initialized htpasswd entry for user '{username}'")
    else:
        print(f"  ERROR: Failed to generate htpasswd entry: {res.stderr}")
        sys.exit(1)
else:
    print(f"  Radicale users file present at {users_file}")
