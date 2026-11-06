# Podman Server Infrastructure

Personal self-hosted server infrastructure managed with [Podman](https://podman.io/) (rootless by default) and [systemd quadlets](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html). The `./install` script is the single entry point that wires up, builds, and deploys all services and custom applications.

---

## Developer & AI Quick Reference

* **Architecture:** Nothing is built or generated into this repository directory. Quadlet files are written directly to their systemd destination directories (`~/.config/containers/systemd/` for user, `/etc/containers/systemd/` for root).
* **Logs & State:** Persistent logs and installer state are tracked at `~/.local/state/podman-server/`.
* **Idempotency:** `./install` is completely idempotent and safe to re-run anytime after configuration or code changes.

### Key Commands

```bash
# Full install / redeploy all enabled services and custom apps
./install

# Deploy and restart all custom apps in apps/
./install apps

# Deploy and restart a single service or app
./install <service-name>

# Manual updates & backups
./update                           # update container images from repo
podman-server-update               # update from anywhere (~/.local/bin)
podman-server-backup               # trigger database backup (~/.local/bin)

# Service inspection
podman ps                          # user-level containers
sudo podman ps                     # root-level containers (plex, scrutiny, homeassistant)
systemctl --user status <service>  # inspect user service
sudo systemctl status <service>    # inspect root service
podman logs <container-name>       # container logs

# Installer & update logs
cat ~/.local/state/podman-server/install.log
cat ~/.local/state/podman-server/update.log
```

---

## Project Structure

```
server/
├── assets/
│   ├── quadlets/          # standard user-level quadlets (tracked in git)
│   ├── quadlets_root/     # root-level quadlets (plex, scrutiny, etc.)
│   └── hooks/             # pre/post deploy lifecycle hooks
├── config/
│   ├── config.yaml        # service registry and directory path mappings
│   ├── secrets.yaml       # plaintext secret values (gitignored)
│   ├── secrets.yaml.age   # age-encrypted secrets (safe to commit)
│   └── secrets.template.yaml
├── helpers/
│   ├── install.py         # core installer and deployment logic
│   ├── update.py          # image update utility (copied to ~/.local/bin)
│   ├── backup.py          # automated database backup utility
│   └── state.py           # execution state cache
├── scripts/
│   ├── encrypt_secrets.py # encrypt secrets.yaml -> secrets.yaml.age
│   └── decrypt_secrets.py # decrypt secrets.yaml.age -> secrets.yaml
├── install                # CLI wrapper -> helpers/install.py
└── update                 # CLI wrapper -> helpers/update.py
```

---

## Custom In-House Applications (`apps/`)

Beside standard upstream container images, the server automatically manages custom in-house applications located in `apps_dir` (`/mnt/Personal/Projects/apps/`):

```
apps/
├── resident_schedule/
│   ├── Containerfile
│   ├── resident-schedule.pre.py    # optional pre-hook / data init
│   └── resident-schedule.container # colocated quadlet
├── census_calc/
│   ├── Containerfile
│   └── census-calculator.container
└── ...
```

### Auto-Discovery & Auto-Build
* **Auto-Discovery:** `./install` automatically scans subdirectories in `apps_dir` for matching `.container` files.
* **Auto-Build:** If a `Containerfile` or `Dockerfile` is present in the app directory, `./install` automatically executes `podman build -t localhost/<name>:latest .` before activating the service.
* **Pre-Hooks:** If `<name>.pre.py` or `pre.py` exists in the app folder, it runs prior to deployment (e.g. to copy default seed data to host volumes).

### Root vs. User Quadlet Scope in Apps
* **User Quadlet (Default):** Any standard `<name>.container` is deployed as a rootless user service (`~/.config/containers/systemd/`).
* **Root Quadlet:** If a file is named `<name>.root.container` / `<name>.system.container`, OR if it contains `# Scope: root` in its header, the installer automatically routes it to `/etc/containers/systemd/` as a system service.

---

## Root vs. User System Services

Most services run as rootless user containers. A few services require root systemd execution:

| Service | Level | Reason |
|---------|-------|--------|
| `plex` | root | GPU hardware transcoding passthrough (`/dev/dri`) |
| `scrutiny` | root | Raw SMART disk access (`/dev/sda`, `AddCapability=SYS_RAWIO`) |
| `homeassistant` | root | Local device discovery (`Network=host`, mDNS/SSDP) |
| `all others` | user | Standard unprivileged rootless containers |

Root services are deployed to `/etc/containers/systemd/` and persistent symlinks are placed in `/etc/systemd/system/default.target.wants/` to guarantee reliable autostart on boot.

---

## Networks & Reverse Proxy

Two isolated Podman networks are deployed automatically from `assets/quadlets/*.network`:

| Network | Purpose |
|---------|---------|
| `frontend` | User-facing web services and reverse proxies (`newt`, `homepage`, web apps) |
| `backend` | Internal database and cache services (PostgreSQL, MariaDB, Redis) |

* **Inter-container communication:** Containers on the same network communicate directly by their `ContainerName` (e.g. `tududi_db:5432`, `immich_redis:6379`, `ollama:11434`).
* **External Tunneling:** The `newt` container runs on `frontend.network` and tunnels traffic from the Pangolin VPS securely to user containers without opening router ports. Root containers running with `Network=host` are reached via `host.containers.internal:<port>`.

---

## Automated Timers

1. **Container Image Updates (`podman-update.timer`):**
   * Runs weekly on Sundays at 3:00 AM.
   * Executes `~/.local/bin/podman-server-update`.
   * Automatically skips `localhost/` images and only pulls updated tags for upstream containers.
2. **Database Backups (`podman-backup.timer`):**
   * Runs daily at 2:00 AM.
   * Executes `~/.local/bin/podman-server-backup`.

---

## Configuration & Secrets

### `config/config.yaml`
Controls base directory paths and which services are enabled:
```yaml
global:
  directories:
    data_dir: "/mnt/containers/data"   # {DATA_DIR} persistent application data
    cloud_dir: "/mnt/containers/cloud" # {CLOUD_DIR} cloud-synced storage
    media_dir: "/mnt/containers/media" # {MEDIA_DIR} media libraries
    apps_dir: "/mnt/Personal/Projects/apps" # custom in-house projects

services:
  immich: { enabled: true }
  calibre-web: { enabled: true }
  resident-schedule: { enabled: true }
```

### Secrets Management
* Secrets are stored in `config/secrets.yaml` (gitignored).
* Copied and synced into both the user and root Podman secret stores on every `./install` run.
* **Encryption:** Run `python3 scripts/encrypt_secrets.py` to produce `config/secrets.yaml.age` (encrypted with Age) to commit secrets safely. `./install` detects and decrypts the `.age` file on demand.

Injected into Quadlet `.container` files via:
```ini
Secret=my_secret_key,type=env,target=ENV_VARIABLE_NAME
```

---

## Adding a New Service

### Adding an Upstream Container
1. Create `assets/quadlets/<service-name>.container` (or in `quadlets_root/` if requiring root device privileges).
2. Use path placeholders like `{DATA_DIR}/<name>/data:/app/data:Z`.
3. Enable in `config/config.yaml`: `<service-name>: { enabled: true }`.
4. Deploy: `./install <service-name>`.

### Adding a Local In-House App
1. Create or clone the repository into `/mnt/Personal/Projects/apps/<app-name>/`.
2. Add a `Containerfile` and `<app-name>.container` directly in the app folder.
3. Enable in `config/config.yaml`: `<app-name>: { enabled: true }`.
4. Deploy: `./install apps` or `./install <app-name>`.
