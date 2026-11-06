#!/usr/bin/env python3

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
import yaml

from state import is_done, mark_done, mark_failed, mark_skipped

logger = logging.getLogger(__name__)

SCRIPT_DIR        = Path(__file__).parent.parent.resolve()
ASSETS_DIR        = SCRIPT_DIR / "assets"
CONFIG_DIR        = SCRIPT_DIR / "config"
HOOKS_DIR         = ASSETS_DIR / "hooks"
SERVICES_CFG_DIR  = CONFIG_DIR / "services"

LOGS_DIR         = Path.home() / ".local/state/podman-server"
UPDATE_BIN       = Path.home() / ".local/bin/podman-server-update"
BACKUP_BIN       = Path.home() / ".local/bin/podman-server-backup"
USER_QUADLETS    = Path.home() / ".config/containers/systemd"
ROOT_QUADLETS    = Path("/etc/containers/systemd")
ROOT_WANTS_DIR   = Path("/etc/systemd/system/default.target.wants")


def run(cmd, input_text=None, check=True):
    return subprocess.run(cmd, input=input_text, text=True, capture_output=True, check=check)


def run_sudo(cmd, input_text=None, check=True):
    return run(["sudo"] + cmd, input_text=input_text, check=check)


def step(msg):
    print(f"\n==> {msg}")


def run_step(name, func):
    if is_done(name):
        print(f"  Skipping {name} (already done)")
        return
    try:
        func()
        mark_done(name)
    except Exception as e:
        mark_failed(name)
        print(f"  FAILED {name}: {e}")
        logger.exception(f"Step '{name}' failed")


# --- Steps ---

def install_podman():
    step("Installing Podman")
    if run(["which", "podman"], check=False).returncode == 0:
        print("  Already installed")
        return
    print("  Installing via pacman...")
    run_sudo(["pacman", "-S", "podman", "--needed", "--noconfirm"])


def setup_quadlet_dirs():
    step("Setting up quadlet directories")

    # Convert legacy symlink to real directory if needed
    if USER_QUADLETS.is_symlink():
        USER_QUADLETS.unlink()
    USER_QUADLETS.mkdir(parents=True, exist_ok=True)
    print(f"  {USER_QUADLETS}")

    if ROOT_QUADLETS.is_symlink():
        run_sudo(["rm", str(ROOT_QUADLETS)])
    elif not ROOT_QUADLETS.exists():
        run_sudo(["mkdir", "-p", str(ROOT_QUADLETS)])
    print(f"  {ROOT_QUADLETS}")


def setup_sudoers():
    if Path("/etc/sudoers.d/podman-server").exists():
        return
    step("Configuring passwordless sudo for systemctl, podman, and tar")
    sudoers_content = "ajay ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/podman, /usr/bin/tar\n"
    run_sudo(["tee", "/etc/sudoers.d/podman-server"], input_text=sudoers_content)
    print("  Created /etc/sudoers.d/podman-server")



def install_update_timer():
    if Path("/etc/systemd/system/podman-update.timer").exists():
        return
    step("Installing update script and timer")

    # Install standalone update script
    UPDATE_BIN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_DIR / "helpers/update.py", UPDATE_BIN)
    UPDATE_BIN.chmod(0o755)
    print(f"  Installed: {UPDATE_BIN}")

    service_content = (
        "[Unit]\n"
        "Description=Podman container image updater\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "User=ajay\n"
        f"ExecStart={UPDATE_BIN}\n"
    )
    timer_content = (
        "[Unit]\n"
        "Description=Weekly podman container image update\n\n"
        "[Timer]\n"
        "OnCalendar=Sun *-*-* 03:00:00\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    run_sudo(["tee", "/etc/systemd/system/podman-update.service"], input_text=service_content)
    run_sudo(["tee", "/etc/systemd/system/podman-update.timer"],   input_text=timer_content)
    try:
        run_sudo(["systemctl", "daemon-reload"])
    except Exception as e:
        print(f"  Warning: Root systemd daemon-reload skipped: {e}")
    run_sudo(["systemctl", "enable", "--now", "podman-update.timer"])
    print("  Installed: podman-update.timer (Sundays 3am)")


def install_backup_timer():
    if Path("/etc/systemd/system/podman-backup.timer").exists():
        return
    step("Installing backup script and timer")

    # Install standalone backup script
    BACKUP_BIN.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_DIR / "helpers/backup.py", BACKUP_BIN)
    BACKUP_BIN.chmod(0o755)
    print(f"  Installed: {BACKUP_BIN}")

    service_content = (
        "[Unit]\n"
        "Description=Podman server data directory backup utility\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "User=ajay\n"
        f"ExecStart={BACKUP_BIN}\n"
    )
    timer_content = (
        "[Unit]\n"
        "Description=Daily podman container database backup\n\n"
        "[Timer]\n"
        "OnCalendar=*-*-* 02:00:00\n"
        "Persistent=true\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    run_sudo(["tee", "/etc/systemd/system/podman-backup.service"], input_text=service_content)
    run_sudo(["tee", "/etc/systemd/system/podman-backup.timer"],   input_text=timer_content)
    try:
        run_sudo(["systemctl", "daemon-reload"])
    except Exception as e:
        print(f"  Warning: Root systemd daemon-reload skipped: {e}")
    run_sudo(["systemctl", "enable", "--now", "podman-backup.timer"])
    print("  Installed: podman-backup.timer (Daily 2am)")


def reload_daemons():
    step("Reloading systemd daemons")
    run(["systemctl", "--user", "daemon-reload"])
    try:
        run_sudo(["systemctl", "daemon-reload"])
    except Exception as e:
        print(f"  Warning: Root systemd daemon-reload skipped: {e}")
    print("  Done")


def substitute(content, dirs):
    return (
        content
        .replace("{DATA_DIR}", dirs["data_dir"])
        .replace("{CLOUD_DIR}", dirs["cloud_dir"])
        .replace("{MEDIA_DIR}", dirs["media_dir"])
    )


def deploy_networks(dirs):
    deployed = []
    USER_QUADLETS.mkdir(parents=True, exist_ok=True)
    for src in sorted((ASSETS_DIR / "quadlets").glob("*.network")):
        dest = USER_QUADLETS / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(substitute(src.read_text(), dirs))
        deployed.append(src.stem)
        print(f"  {src.name}")
    return deployed


def ensure_volume_dirs(content, is_root):
    for line in content.splitlines():
        if not line.startswith("Volume="):
            continue
        host_path = line.split("=", 1)[1].strip().split(":")[0]
        if not host_path.startswith("/"):
            continue
        p = Path(host_path)
        if p.exists() and not p.is_dir():
            continue  # file bind-mount (e.g. /etc/localtime), not a dir to create
        if is_root:
            run_sudo(["mkdir", "-p", host_path])
        else:
            p.mkdir(parents=True, exist_ok=True)
        print(f"  mkdir {host_path}")


def is_root_quadlet(src: Path) -> bool:
    name = src.name.lower()
    if ".root." in name or ".system." in name:
        return True
    try:
        content = src.read_text()
        for line in content.splitlines():
            line = line.strip().lower()
            if line.startswith("#") and ("scope: root" in line or "scope=root" in line):
                return True
            if line.startswith("scope=root") or line.startswith("x-scope=root"):
                return True
    except Exception:
        pass
    return False


def find_service_assets(name, apps_dir):
    """Find container and volume assets for service `name` across quadlet folders and apps_dir."""
    # 1. Root assets in server repo
    root_src = ASSETS_DIR / "quadlets_root" / f"{name}.container"
    if root_src.exists():
        return [(root_src, True)]

    # 2. Standard user assets in server repo
    user_dir = ASSETS_DIR / "quadlets"
    user_containers = sorted(user_dir.glob(f"{name}.container")) + sorted(user_dir.glob(f"{name}-*.container"))
    user_volumes    = sorted(user_dir.glob(f"{name}*.volume"))
    if user_containers or user_volumes:
        return [(src, False) for src in user_containers + user_volumes]

    # 3. App subdirectories in apps_dir
    if apps_dir and apps_dir.exists():
        app_assets = []
        for app_dir in sorted(apps_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            matched = (
                sorted(app_dir.glob(f"{name}.container")) +
                sorted(app_dir.glob(f"{name}.root.container")) +
                sorted(app_dir.glob(f"{name}.system.container")) +
                sorted(app_dir.glob(f"{name}-*.container")) +
                sorted(app_dir.glob(f"{name}-*.root.container")) +
                sorted(app_dir.glob(f"{name}-*.system.container")) +
                sorted(app_dir.glob(f"{name}*.volume"))
            )
            for src in matched:
                app_assets.append((src, is_root_quadlet(src)))
        if app_assets:
            return app_assets

    return []


def deploy_service(name, dirs):
    """Returns (level, [service_names]) or (None, []) if no assets found."""
    apps_dir = Path(dirs.get("apps_dir", SCRIPT_DIR.parent / "apps"))
    assets = find_service_assets(name, apps_dir)

    if not assets:
        print(f"  WARNING: no asset found for '{name}', skipping")
        return None, []

    is_root = any(asset_is_root for _, asset_is_root in assets)
    level = "root" if is_root else "user"
    service_names = []

    for src, asset_is_root in assets:
        content = substitute(src.read_text(), dirs)
        if src.suffix == ".container":
            ensure_volume_dirs(content, is_root=asset_is_root)

        dest_name = src.name.replace(".root.", ".").replace(".system.", ".")

        if asset_is_root:
            dest = ROOT_QUADLETS / dest_name
            run_sudo(["tee", str(dest)], input_text=content)
            print(f"  {dest_name} (root from {src.parent.name})")
            if src.suffix == ".container":
                service_names.append(dest.stem)
        else:
            dest = USER_QUADLETS / dest_name
            dest.write_text(content)
            print(f"  {dest_name} (user from {src.parent.name})")
            if src.suffix == ".container":
                service_names.append(dest.stem)

    return level, service_names


def start_network(name):
    svc = f"{name}-network.service"
    run(["systemctl", "--user", "start", svc])
    print(f"  Started {svc}")


def start_service(level, service_names):
    for svc in service_names:
        if level == "root":
            run_sudo(["systemctl", "start", f"{svc}.service"])
            run_sudo(["mkdir", "-p", str(ROOT_WANTS_DIR)])
            run_sudo(["ln", "-sf",
                      f"/run/systemd/generator/{svc}.service",
                      str(ROOT_WANTS_DIR / f"{svc}.service")])
        else:
            run(["systemctl", "--user", "start", f"{svc}.service"])
        print(f"  Started {svc} ({level})")


HOST_NETWORK_PORTS = {
    "plex": ["32400/tcp"],
    "homeassistant": ["8123/tcp"],
}


def collect_ports(service_names, apps_dir=None):
    """Scan container assets for PublishPort entries and return firewall port strings."""
    ports = set()
    search_dirs = [ASSETS_DIR / "quadlets", ASSETS_DIR / "quadlets_root"]
    if apps_dir and apps_dir.exists():
        search_dirs.extend([d for d in apps_dir.iterdir() if d.is_dir()])

    for name in service_names:
        if name in HOST_NETWORK_PORTS:
            for p in HOST_NETWORK_PORTS[name]:
                ports.add(p)
        for src_dir in search_dirs:
            files = (
                sorted(src_dir.glob(f"{name}.container")) +
                sorted(src_dir.glob(f"{name}-*.container")) +
                sorted(src_dir.glob(f"{name}*.root.container")) +
                sorted(src_dir.glob(f"{name}*.system.container"))
            )
            for f in files:
                for line in f.read_text().splitlines():
                    if not line.startswith("PublishPort="):
                        continue
                    value = line.split("=", 1)[1].strip()
                    host_part, rest = value.split(":", 1)
                    proto = rest.split("/")[1] if "/" in rest else "tcp"
                    ports.add(f"{host_part}/{proto}")
    return sorted(ports)


def open_firewall_ports(ports):
    step("Opening firewall ports")
    for port in ports:
        try:
            run_sudo(["firewall-cmd", "--zone=public", f"--add-port={port}", "--permanent"])
            print(f"  Opened {port}")
        except Exception as e:
            print(f"  Warning: Root firewall-cmd skipped for {port}: {e}")
    try:
        run_sudo(["firewall-cmd", "--reload"])
        print("  Reloaded")
    except Exception as e:
        print(f"  Warning: Root firewall-cmd reload skipped: {e}")


def run_hook(name, phase, dirs):
    apps_dir = Path(dirs.get("apps_dir", SCRIPT_DIR.parent / "apps"))
    hook = None
    app_dir = None

    # 1. Check server HOOKS_DIR
    candidate = HOOKS_DIR / f"{name}.{phase}.py"
    if candidate.exists():
        hook = candidate

    # 2. Check apps_dir
    if not hook and apps_dir.exists():
        for d in sorted(apps_dir.iterdir()):
            if not d.is_dir():
                continue
            candidates = [
                d / f"{name}.{phase}.py",
                d / f"{phase}.py",
            ]
            for c in candidates:
                if c.exists() and (d.name == name or d.name == name.replace("-", "_") or any(d.glob(f"{name}*.container"))):
                    hook = c
                    app_dir = d
                    break
            if hook:
                break

    # 3. If phase is pre and no hook found, but app has Containerfile/Dockerfile, auto-build
    if phase == "pre" and not hook and apps_dir.exists():
        for d in sorted(apps_dir.iterdir()):
            if not d.is_dir():
                continue
            if d.name == name or d.name == name.replace("-", "_") or any(d.glob(f"{name}*.container")):
                dockerfile = d / "Containerfile" if (d / "Containerfile").exists() else (d / "Dockerfile" if (d / "Dockerfile").exists() else None)
                if dockerfile:
                    step(f"Building local image for {name} from {d.name}")
                    cmd = ["podman", "build", "-t", f"localhost/{name}:latest", "."]
                    res = subprocess.run(cmd, cwd=str(d))
                    if res.returncode != 0:
                        print(f"  WARNING: build failed for '{name}', skipping service deployment.")
                        return False
                    print(f"  Built localhost/{name}:latest successfully")
                    return True

    if not hook:
        return True

    step(f"Running {hook.name} hook")
    env = {
        **os.environ,
        "SERVICE_NAME":   name,
        "SERVICE_CONFIG": str(SERVICES_CFG_DIR / f"{name}.yaml"),
        "DATA_DIR":       dirs["data_dir"],
        "MEDIA_DIR":      dirs["media_dir"],
        "CLOUD_DIR":      dirs["cloud_dir"],
        "APPS_DIR":       str(apps_dir),
        "SCRIPT_DIR":     str(SCRIPT_DIR),
    }
    result = subprocess.run([sys.executable, str(hook)], env=env, cwd=str(app_dir or SCRIPT_DIR))
    if result.returncode != 0:
        if phase == "pre":
            print(f"  WARNING: pre-hook failed for '{name}' (exit code {result.returncode}), skipping service deployment.")
            return False
        else:
            print(f"  WARNING: post-hook for '{name}' exited with code {result.returncode}")
            return False
    return True


def sync_secrets(config_dir):
    step("Syncing secrets")

    age_path   = config_dir / "secrets.yaml.age"
    plain_path = config_dir / "secrets.yaml"

    if age_path.exists():
        print("  Decrypting secrets.yaml.age...")
        result = subprocess.run(
            ["age", "--decrypt", str(age_path)],
            stdout=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            print("  Warning: age decryption failed. Skipping secrets sync and proceeding with existing secrets.")
            return
        content = result.stdout
    elif plain_path.exists():
        content = plain_path.read_text()
    else:
        print("  No secrets.yaml or secrets.yaml.age found, skipping")
        return

    data = yaml.safe_load(content)
    secrets = data.get("secrets", {})
    if not secrets:
        print("  No secrets found")
        return
    for name, value in secrets.items():
        if not isinstance(value, str):
            raise ValueError(f"Secret '{name}' must be a string")
        run(["podman", "secret", "create", "--replace", name, "-"], input_text=value)
        run_sudo(["podman", "secret", "create", "--replace", name, "-"], input_text=value)
        print(f"  Synced: {name}")


# --- Main ---

def print_help(services):
    enabled  = [n for n, c in services.items() if n != "networks" and c.get("enabled")]
    disabled = [n for n, c in services.items() if n != "networks" and not c.get("enabled")]
    print("Usage: install [service|help]")
    print()
    print("  install            Full install / redeploy all enabled services")
    print("  install apps       Deploy and start all custom apps in apps/")
    print("  install <service>  Deploy and start a single service")
    print("  install help       Show this help message")
    print()
    print(f"Enabled services:  {', '.join(sorted(enabled))}")
    if disabled:
        print(f"Disabled services: {', '.join(sorted(disabled))}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    config   = yaml.safe_load((CONFIG_DIR / "config.yaml").read_text())
    dirs     = config["global"]["directories"]
    services = config["services"]

    if target in ("help", "--help", "-h"):
        print_help(services)
        sys.exit(0)

    if target == "apps":
        apps_path = Path(dirs.get("apps_dir", SCRIPT_DIR.parent / "apps"))
        app_services = {}
        if apps_path.exists():
            for d in sorted(apps_path.iterdir()):
                if not d.is_dir():
                    continue
                for c in sorted(d.glob("*.container")):
                    svc_name = c.stem.replace(".root", "").replace(".system", "")
                    app_services[svc_name] = services.get(svc_name, {"enabled": True})
        if not app_services:
            print(f"No apps found in {apps_path}")
            sys.exit(0)
        deploy_targets = app_services
    elif target and target not in services:
        print(f"Error: '{target}' not found in config.yaml services")
        print("Run 'install help' to see available services")
        sys.exit(1)
    else:
        deploy_targets = {target: services[target]} if target else services

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=LOGS_DIR / "install.log",
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not target:
        install_podman()
        setup_quadlet_dirs()
        setup_sudoers()
        install_update_timer()
        install_backup_timer()
        reload_daemons()
    else:
        USER_QUADLETS.mkdir(parents=True, exist_ok=True)

    step("Deploying quadlet files")
    network_names  = []
    service_levels = {}

    if not target and services.get("networks", {}).get("enabled"):
        network_names = deploy_networks(dirs)

    failed_services = []
    for name, cfg in deploy_targets.items():
        if name == "networks":
            continue
        if not cfg.get("enabled"):
            mark_skipped(f"service.{name}")
            continue
        if not run_hook(name, "pre", dirs):
            mark_failed(f"service.{name}")
            failed_services.append((name, "pre-hook build failed"))
            continue
        try:
            level, svc_names = deploy_service(name, dirs)
            if level:
                service_levels[name] = (level, svc_names)
        except Exception as e:
            print(f"  ERROR: Failed to deploy service '{name}': {e}")
            mark_failed(f"service.{name}")
            failed_services.append((name, str(e)))
            continue

    reload_daemons()

    sync_secrets(CONFIG_DIR)

    ports = collect_ports(list(service_levels.keys()), apps_dir=Path(dirs.get('apps_dir', SCRIPT_DIR.parent / 'apps')))
    if ports:
        open_firewall_ports(ports)

    step("Starting services")
    for net_name in network_names:
        try:
            start_network(net_name)
        except Exception as e:
            print(f"  Warning: Failed to start network {net_name}: {e}")

    for name, (level, svc_names) in service_levels.items():
        try:
            start_service(level, svc_names)
            mark_done(f"service.{name}")
            run_hook(name, "post", dirs)
        except Exception as e:
            print(f"  FAILED to start {name}: {e}")
            mark_failed(f"service.{name}")
            failed_services.append((name, f"failed to start: {e}"))

    print("\n==> Done")
    if failed_services:
        print("\n⚠️  The following services could not be deployed and were skipped:")
        for s_name, reason in failed_services:
            print(f"   • {s_name}: {reason}")
        print("All other services were processed successfully.")


if __name__ == "__main__":
    main()
