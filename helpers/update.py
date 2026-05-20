#!/usr/bin/env python3
"""
Standalone container image updater. No dependency on the server repo.
Reads deployed quadlets directly from their systemd directories.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

USER_QUADLETS_DIR = Path.home() / ".config/containers/systemd"
ROOT_QUADLETS_DIR = Path("/etc/containers/systemd")
LOG_DIR = Path.home() / ".local/state/podman-server"
LOG_FILE = LOG_DIR / "update.log"

USER_UID = os.getuid()
USER_ENV = {
    **os.environ,
    "XDG_RUNTIME_DIR": f"/run/user/{USER_UID}",
    "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{USER_UID}/bus",
}


def run(cmd, env=None):
    return subprocess.run(cmd, text=True, capture_output=True, env=env or USER_ENV)


def run_sudo(cmd):
    return run(["sudo"] + cmd, env=os.environ)


def log(msg, f):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    f.write(line + "\n")
    f.flush()


def image_from_quadlet(path):
    for line in path.read_text().splitlines():
        if line.startswith("Image="):
            return line.split("=", 1)[1].strip()
    return None


def get_image_id(image, is_root):
    cmd = ["podman", "image", "inspect", image, "--format", "{{.Id}}"]
    result = run_sudo(cmd) if is_root else run(cmd)
    return result.stdout.strip() if result.returncode == 0 else None


def pull_image(image, is_root):
    cmd = ["podman", "pull", image]
    result = run_sudo(cmd) if is_root else run(cmd)
    return result.returncode == 0, result.stderr.strip()


def restart_service(svc, is_root):
    if is_root:
        result = run_sudo(["systemctl", "restart", f"{svc}.service"])
    else:
        result = run(["systemctl", "--user", "restart", f"{svc}.service"])
    return result.returncode == 0


def iter_containers():
    """Yields (quadlet_path, service_name, is_root) for all deployed containers."""
    for path in sorted(USER_QUADLETS_DIR.glob("*.container")):
        yield path, path.stem, False
    for path in sorted(ROOT_QUADLETS_DIR.glob("*.container")):
        yield path, path.stem, True


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    updated = 0
    failed = 0

    with open(LOG_FILE, "a") as f:
        log("=== update started ===", f)

        for quadlet_path, svc_name, is_root in iter_containers():
            image = image_from_quadlet(quadlet_path)
            if not image:
                continue

            if image.startswith("localhost/"):
                log(f"skip {svc_name}: local image", f)
                continue

            old_id = get_image_id(image, is_root)
            ok, err = pull_image(image, is_root)
            if not ok:
                log(f"FAIL pull {svc_name} ({image}): {err}", f)
                failed += 1
                continue

            new_id = get_image_id(image, is_root)
            if old_id == new_id:
                log(f"ok   {svc_name}: up to date", f)
                continue

            short = lambda x: x[:12] if x else "none"
            log(f"NEW  {svc_name}: {short(old_id)} -> {short(new_id)}", f)
            if restart_service(svc_name, is_root):
                log(f"     restarted {svc_name}", f)
                updated += 1
            else:
                log(f"FAIL restart {svc_name}", f)
                failed += 1

        log(f"=== done: {updated} updated, {failed} failed ===", f)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
