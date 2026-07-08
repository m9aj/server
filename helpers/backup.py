#!/usr/bin/env python3
"""
Standalone podman server backup utility.
Reads active services from config.yaml, stops them, backs up the data directory,
saves the archive to the cloud or data backups folder, applies retention, and restarts services.
"""

import os
import subprocess
import sys
import tarfile
import shutil
from datetime import datetime
from pathlib import Path
import yaml

CONFIG_PATH = Path("/home/ajay/Arch/server/config/config.yaml")
USER_QUADLETS_DIR = Path.home() / ".config/containers/systemd"
ROOT_QUADLETS_DIR = Path("/etc/containers/systemd")
LOG_DIR = Path.home() / ".local/state/podman-server"
LOG_FILE = LOG_DIR / "backup.log"

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

def iter_deployed_services():
    """Yields (service_name, is_root) for all deployed containers."""
    for path in sorted(USER_QUADLETS_DIR.glob("*.container")):
        yield path.stem, False
    for path in sorted(ROOT_QUADLETS_DIR.glob("*.container")):
        yield path.stem, True

def manage_service(svc, action, is_root, f):
    log(f"{action}ing {svc}...", f)
    if is_root:
        result = run_sudo(["systemctl", action, f"{svc}.service"])
    else:
        result = run(["systemctl", "--user", action, f"{svc}.service"])
    
    if result.returncode == 0:
        log(f"Successfully {action}ed {svc}", f)
        return True
    else:
        log(f"FAIL to {action} {svc}: {result.stderr.strip()}", f)
        return False

def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(LOG_FILE, "a") as f:
        log("=== backup started ===", f)
        
        # Load config
        if not CONFIG_PATH.exists():
            log(f"ERROR: config file not found at {CONFIG_PATH}", f)
            return 1
            
        try:
            with open(CONFIG_PATH, "r") as cfg_file:
                config = yaml.safe_load(cfg_file)
        except Exception as e:
            log(f"ERROR reading config: {e}", f)
            return 1
            
        global_dirs = config.get("global", {}).get("directories", {})
        data_dir_str = global_dirs.get("data_dir", "/mnt/containers/data")
        cloud_dir_str = global_dirs.get("cloud_dir", "/mnt/containers/cloud")
        
        data_dir = Path(data_dir_str)
        cloud_dir = Path(cloud_dir_str)
        
        if not data_dir.exists():
            log(f"ERROR: data directory {data_dir} does not exist", f)
            return 1
            
        # Determine backup destination
        backup_dir = cloud_dir / "backups"
        if not cloud_dir.exists() or not os.access(cloud_dir, os.W_OK):
            backup_dir = data_dir / "backups"
            
        backup_dir.mkdir(parents=True, exist_ok=True)
        log(f"Backup destination directory: {backup_dir}", f)
        
        # 1. Stop all currently deployed services
        services = list(iter_deployed_services())
        stopped_services = []
        
        log(f"Found {len(services)} active service(s) to pause.", f)
        for svc_name, is_root in services:
            # Skip networks or helper systems if they don't run as containers
            if svc_name == "networks":
                continue
            if manage_service(svc_name, "stop", is_root, f):
                stopped_services.append((svc_name, is_root))
                
        # 2. Perform the backup archive
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_{timestamp}.tar.gz"
        backup_filepath = backup_dir / backup_filename
        
        log(f"Archiving data directory {data_dir} to {backup_filepath}...", f)
        try:
            # Determine exclusions based on config.yaml services
            excludes = []
            services = config.get("services", {})
            for name, svc_cfg in services.items():
                if isinstance(svc_cfg, dict) and svc_cfg.get("backup") is False:
                    excludes.append(name)
            if excludes:
                log(f"Excluding directories from backup: {', '.join(excludes)}", f)
        except Exception as e:
            log(f"Warning: error parsing service exclusions: {e}", f)
            excludes = []

        try:
            # We run the archiving process using 'sudo tar' to ensure we can read
            # all files (both rootless shifted files and rootful files).
            cmd = [
                "sudo", "tar", "-czf", str(backup_filepath),
                "--exclude=backups",
                "--exclude=*.sock",
            ]
            for exc in excludes:
                cmd.append(f"--exclude={exc}")
            cmd.extend([
                "-C", str(data_dir),
                "."
            ])
            result = run(cmd)
            if result.returncode == 0:
                log("Archive created successfully.", f)
            else:
                log(f"ERROR creating archive: {result.stderr.strip()}", f)
        except Exception as e:
            log(f"ERROR creating archive: {e}", f)
            
        # 3. Restart the services in reverse order
        log("Restarting stopped services...", f)
        for svc_name, is_root in reversed(stopped_services):
            manage_service(svc_name, "start", is_root, f)
            
        # 4. Apply retention policy (Keep last 7 backups)
        try:
            all_backups = sorted(list(backup_dir.glob("backup_*.tar.gz")))
            log(f"Retention check: found {len(all_backups)} backups.", f)
            if len(all_backups) > 7:
                to_delete = all_backups[:-7]
                for old_b in to_delete:
                    old_b.unlink()
                    log(f"Removed old backup: {old_b.name}", f)
        except Exception as e:
            log(f"ERROR applying retention policy: {e}", f)
            
        log("=== backup completed ===", f)
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
