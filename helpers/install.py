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
    run_sudo(["mkdir", "-p", str(ROOT_QUADLETS)])
    print(f"  {ROOT_QUADLETS}")


def setup_sudoers():
    step("Configuring passwordless sudo for systemctl, podman, and tar")
    sudoers_content = "ajay ALL=(ALL) NOPASSWD: /usr/bin/systemctl, /usr/bin/podman, /usr/bin/tar\n"
    run_sudo(["tee", "/etc/sudoers.d/podman-server"], input_text=sudoers_content)
    print("  Created /etc/sudoers.d/podman-server")



def install_update_timer():
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


def deploy_service(name, dirs):
    """Returns (level, [service_names]) or (None, []) if no assets found."""

    root_src = ASSETS_DIR / "quadlets_root" / f"{name}.container"
    if root_src.exists():
        content = substitute(root_src.read_text(), dirs)
        ensure_volume_dirs(content, is_root=True)
        dest = ROOT_QUADLETS / root_src.name
        run_sudo(["tee", str(dest)], input_text=content)
        print(f"  {root_src.name} (root)")
        return "root", [name]

    user_dir = ASSETS_DIR / "quadlets"
    containers = sorted(user_dir.glob(f"{name}.container")) + sorted(user_dir.glob(f"{name}-*.container"))
    volumes    = sorted(user_dir.glob(f"{name}*.volume"))

    if not containers and not volumes:
        print(f"  WARNING: no asset found for '{name}', skipping")
        return None, []

    service_names = []
    for src in containers + volumes:
        content = substitute(src.read_text(), dirs)
        if src.suffix == ".container":
            ensure_volume_dirs(content, is_root=False)
        dest = USER_QUADLETS / src.name
        dest.write_text(content)
        print(f"  {src.name} (user)")
        if src.suffix == ".container":
            service_names.append(src.stem)

    return "user", service_names


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


def collect_ports(service_names):
    """Scan container assets for PublishPort entries and return firewall port strings."""
    ports = set()
    for name in service_names:
        if name in HOST_NETWORK_PORTS:
            for p in HOST_NETWORK_PORTS[name]:
                ports.add(p)
        for src_dir in [ASSETS_DIR / "quadlets", ASSETS_DIR / "quadlets_root"]:
            files = sorted(src_dir.glob(f"{name}.container")) + sorted(src_dir.glob(f"{name}-*.container"))
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
    hook = HOOKS_DIR / f"{name}.{phase}.py"
    if not hook.exists():
        return True
    step(f"Running {name}.{phase} hook")
    env = {
        **os.environ,
        "SERVICE_NAME":   name,
        "SERVICE_CONFIG": str(SERVICES_CFG_DIR / f"{name}.yaml"),
        "DATA_DIR":       dirs["data_dir"],
        "MEDIA_DIR":      dirs["media_dir"],
        "CLOUD_DIR":      dirs["cloud_dir"],
        "APPS_DIR":       dirs.get("apps_dir", str(SCRIPT_DIR.parent / "apps")),
        "SCRIPT_DIR":     str(SCRIPT_DIR),
    }
    result = subprocess.run([sys.executable, str(hook)], env=env)
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

    if target and target not in services:
        print(f"Error: '{target}' not found in config.yaml services")
        print("Run 'install help' to see available services")
        sys.exit(1)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=LOGS_DIR / "install.log",
        level=logging.ERROR,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    install_podman()
    setup_quadlet_dirs()
    setup_sudoers()
    install_update_timer()
    install_backup_timer()

    reload_daemons()

    step("Deploying quadlet files")
    network_names  = []
    service_levels = {}

    if not target and services.get("networks", {}).get("enabled"):
        network_names = deploy_networks(dirs)

    failed_services = []
    deploy_targets = {target: services[target]} if target else services
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

    ports = collect_ports(list(service_levels.keys()))
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
