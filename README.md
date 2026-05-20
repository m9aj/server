# Podman Server Infrastructure

Personal self-hosted server stack managed with [Podman](https://podman.io/) and [systemd quadlets](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html).

## Prerequisites

- Arch Linux (installer uses `pacman`)
- `python-yaml` (`sudo pacman -S python-yaml`)
- `config/secrets.yaml` populated (see [Secrets](#secrets))

## Install

```bash
./install
```

Idempotent — safe to re-run after config changes. It will:

1. Install Podman if not already present
2. Ensure quadlet destination directories exist (`~/.config/containers/systemd/`, `/etc/containers/systemd/`)
3. Copy enabled service templates from `assets/` into those directories, substituting path variables
4. Reload systemd daemons (user + root) and start all enabled services
5. Sync secrets from `config/secrets.yaml` into Podman's secret store
6. Install the update script to `~/.local/bin/podman-server-update` and schedule a weekly systemd timer

To redeploy a single service:

```bash
./install <service-name>
```

## Updates

Container images are updated automatically every Sunday at 3am via a systemd timer. The timer runs `~/.local/bin/podman-server-update`, which is installed independently of this repo — updates continue to run even if this directory is moved or deleted.

To trigger an update manually:

```bash
./update
# or from anywhere:
podman-server-update
```

Logs are written to `~/.local/state/podman-server/update.log`.

## Configuration

**`config/config.yaml`** — controls which services are deployed and where data lives:

```yaml
global:
  directories:
    data_dir: "/mnt/containers/data"   # persistent app data
    cloud_dir: "/mnt/containers/cloud" # cloud-synced data
    media_dir: "/mnt/containers/media" # media library

services:
  myapp: { enabled: true }
```

**`config/secrets.yaml`** (gitignored) — values synced into Podman's secret store. Copy from `config/secrets.template.yaml` to get started:

```yaml
secrets:
  my_secret_name: "value"
```

Secrets are injected into containers via:
```ini
Secret=my_secret_name,type=env,target=ENV_VAR_NAME
```

To encrypt secrets with [age](https://age-encryption.org/) for safe storage in version control:

```bash
# Encrypt (produces config/secrets.yaml.age — commit this)
python3 scripts/encrypt_secrets.py

# Decrypt back to plaintext for editing
python3 scripts/decrypt_secrets.py
```

`./install` automatically detects and decrypts `secrets.yaml.age` at install time (prompts for passphrase). Falls back to plain `secrets.yaml` if no `.age` file is present.

## Adding a New Service

### 1. Create the quadlet template

For most services, create `assets/quadlets/<name>.container`:

```ini
[Unit]
Description=My App
After=systemd-networkd.service frontend-network.service

[Container]
Image=docker.io/org/image:latest
ContainerName=myapp
Volume={DATA_DIR}/myapp/data:/data:Z
Network=frontend.network

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Use `{DATA_DIR}`, `{MEDIA_DIR}`, or `{CLOUD_DIR}` for mount paths — substituted from `config/config.yaml` at install time.

For services that need device access or must run as root (like Plex, Scrutiny, Pi-hole), put the file in `assets/quadlets_root/` instead.

### 2. Multi-container services

If the service needs multiple containers (e.g. app + database + cache), create one file per container, all prefixed with the service name:

```
assets/quadlets/myapp.container
assets/quadlets/myapp-db.container
assets/quadlets/myapp-redis.container
assets/quadlets/myapp-data.volume      # optional named volume
```

The installer deploys and starts all files matching `myapp*.container` and `myapp*.volume` from a single config entry.

Wire dependencies between containers using `Requires=` and `After=`:

```ini
# myapp.container
After=... myapp-db.service myapp-redis.service
Requires=myapp-db.service myapp-redis.service
```

Containers on the same network communicate by `ContainerName`.

### 3. Add secrets (if needed)

Add entries to `config/secrets.yaml`:

```yaml
secrets:
  myapp_api_key: "your-key-here"
```

Reference them in the quadlet:

```ini
Secret=myapp_api_key,type=env,target=API_KEY
```

### 4. Register in config.yaml

```yaml
myapp: { enabled: true }
```

### 5. Deploy

```bash
./install myapp
```

## Networks

Two shared Podman networks created automatically:

| Network    | Purpose |
|------------|---------|
| `frontend` | User-facing services — attach here if behind a reverse proxy |
| `backend`  | Internal services — databases, caches, ML workers |

Services on the same network reach each other by `ContainerName`.

## Tunneling (Pangolin / Newt)

User-facing services are exposed via a [Pangolin](https://github.com/fosrl/pangolin) tunnel (`newt` client running as a user container on `frontend.network`). Root-level services (Pi-hole, Scrutiny) run with `Network=host` and are not on any Podman network — reach them from within the tunnel using the special hostname `host.containers.internal` (e.g. `host.containers.internal:8081`).

## Root vs User Services

| Service   | Level | Reason |
|-----------|-------|--------|
| plex      | root  | GPU device passthrough (`/dev/dri`) |
| scrutiny  | root  | Raw disk access (`/dev/sda`, `AddCapability=SYS_RAWIO`) |
| pihole    | root  | Binds to host port 53 (DNS) |
| all others | user | Standard rootless containers |

Root services get persistent boot symlinks installed to `/etc/systemd/system/default.target.wants/` so they auto-start reliably across reboots.

## Useful Commands

```bash
# Check running containers
podman ps                        # user
sudo podman ps                   # root

# View logs
podman logs <container-name>

# Check service status
systemctl --user status <service>
sudo systemctl status <service>  # root services

# Restart a service
systemctl --user restart <service>
sudo systemctl restart <service> # root services

# Check update timer
systemctl status podman-update.timer
cat ~/.local/state/podman-server/update.log
```

## Project Structure

```
assets/
  quadlets/          # user-level quadlet templates (tracked in git)
  quadlets_root/     # root-level quadlet templates (tracked in git)
  hooks/             # pre/post deploy hooks per service
config/
  config.yaml        # service registry and directory config
  secrets.yaml       # secret values (gitignored)
  secrets.yaml.age   # age-encrypted secrets (commit this instead)
  secrets.template.yaml  # template listing all required secret keys
helpers/
  install.py         # installer logic
  update.py          # update logic (copied to ~/.local/bin at install time)
scripts/
  encrypt_secrets.py # encrypt secrets.yaml → secrets.yaml.age
  decrypt_secrets.py # decrypt secrets.yaml.age → secrets.yaml
  github_download.sh # clone/pull this repo on a fresh machine
install              # entry point → helpers/install.py
update               # manual update entry point → helpers/update.py
```

Generated quadlet files go directly to `~/.config/containers/systemd/` (user) and `/etc/containers/systemd/` (root) — nothing is generated inside this repo.

Logs and install state are stored at `~/.local/state/podman-server/`.
