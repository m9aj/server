# Instructions.md

This file provides guidance for developers and AI assistants when working with code in this repository.

## Project Overview

Personal server infrastructure using **Podman** (rootless) and **systemd quadlets** to manage ~23 self-hosted services. `./install` is the single entry point that wires everything together from scratch.

## Key Commands

```bash
# Full install / re-deploy (idempotent)
./install

# Deploy and restart a single service
./install <service-name>

# Manually run image updates
./update                      # from this repo
podman-server-update          # from anywhere (installed to ~/.local/bin)

# Runtime inspection
podman ps                     # user containers
sudo podman ps                # root containers (plex, scrutiny, pihole)
systemctl --user status <service>
sudo systemctl status <service>
podman logs <container-name>

# Check update logs
cat ~/.local/state/podman-server/update.log
```

## Architecture

### Directory Structure

```
assets/
  quadlets/          # user-level quadlet templates (tracked in git)
  quadlets_root/     # root-level quadlet templates (tracked in git)
config/
  config.yaml        # which services to deploy + mount path config
  secrets.yaml       # Podman secrets (gitignored)
helpers/
  install.py         # installer logic
  update.py          # standalone update script (copied to ~/.local/bin at install)
install              # bash entry point → helpers/install.py
update               # bash entry point → helpers/update.py
```

Nothing is generated inside this repo. Quadlet files are written directly to their systemd destinations. Logs and state live at `~/.local/state/podman-server/`.

### Install Flow (`helpers/install.py`)

1. Installs Podman via pacman if missing
2. Ensures `~/.config/containers/systemd/` and `/etc/containers/systemd/` exist (converts legacy symlinks if present)
3. Copies `helpers/update.py` to `~/.local/bin/podman-server-update` and installs a weekly systemd timer (`podman-update.timer`)
4. Reloads systemd (user + root)
5. For each enabled service in `config/config.yaml`:
   - Checks `assets/quadlets_root/<name>.container` first (root), then user-level
   - For user-level: matches `<name>.container` exactly, then `<name>-*.container` and `<name>*.volume` for multi-container stacks
   - Writes directly to the systemd destination, substituting `{DATA_DIR}`, `{MEDIA_DIR}`, `{CLOUD_DIR}` from `config.yaml`
6. Reloads daemons again, starts networks then all matched service units
7. For root services, creates persistent boot symlinks in `/etc/systemd/system/default.target.wants/`
8. Syncs secrets from `config/secrets.yaml` into Podman's secret store (both user and root stores)

Steps 1–3 are cached via `~/.local/state/podman-server/state.json` and only run once.

### Update Flow (`helpers/update.py`)

Standalone — no dependency on this repo. Reads deployed quadlets directly from their systemd directories:
- `~/.config/containers/systemd/*.container` → user services
- `/etc/containers/systemd/*.container` → root services

For each container, pulls the image, compares digest before/after, and restarts the service if the image changed. Logs to `~/.local/state/podman-server/update.log`. Scheduled weekly via `podman-update.timer`.

### Quadlet Templates

Asset files use three path placeholders substituted at install time:
- `{DATA_DIR}` — application data (`/mnt/containers/data`)
- `{MEDIA_DIR}` — media files (`/mnt/containers/media`)
- `{CLOUD_DIR}` — cloud-synced data (`/mnt/containers/cloud`)

### Root vs User Services

The installer checks `assets/quadlets_root/` first. If a file exists there it is deployed as a root systemd service (written via `sudo`, started with `sudo systemctl`). Root services also get a persistent symlink in `/etc/systemd/system/default.target.wants/` to ensure reliable boot autostart.

Current root services: `plex` (GPU passthrough), `scrutiny` (raw disk access), `pihole` (host port 53).

### Networking

Two Podman networks deployed from `assets/quadlets/*.network`:
- `frontend` — all user-facing web services attach here
- `backend` — internal services (reserved for future use)

The `newt` (Pangolin tunnel) container runs on `frontend.network` and proxies traffic from the Pangolin VPS to user containers. Root services use `Network=host` and are not on any Podman network — they are reachable from the tunnel using `host.containers.internal:<port>`.

### Secrets

Defined in `config/secrets.yaml` (gitignored), synced into both the user and root Podman secret stores on every install. Injected into containers via:
```ini
Secret=secret_name,type=env,target=ENV_VAR_NAME
```
