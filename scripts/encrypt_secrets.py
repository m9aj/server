#!/usr/bin/env python3
"""Encrypt sensitive config files with age (passphrase mode).

Files encrypted: secrets.yaml
Outputs:         *.yaml.age alongside each source file
"""

import os
import sys
import pty
import fcntl
import termios
import subprocess
import getpass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")

SENSITIVE_FILES = [
    "secrets.yaml",
]


def _check_age():
    if subprocess.run(["which", "age"], capture_output=True).returncode != 0:
        print("ERROR: age is not installed. Install it with: pacman -S age")
        sys.exit(1)


def _age_run(args, passphrase, write_count=1):
    """Run age with passphrase fed via PTY as the child's controlling terminal."""
    master_fd, slave_fd = pty.openpty()

    def _preexec():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        args,
        stdin=slave_fd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=_preexec,
    )
    os.close(slave_fd)
    os.write(master_fd, ((passphrase + "\n") * write_count).encode())
    stdout, stderr = proc.communicate()
    os.close(master_fd)
    return proc.returncode, stdout, stderr


def _encrypt(path, passphrase):
    out_path = path + ".age"
    rc, _, stderr = _age_run(
        ["age", "--encrypt", "--passphrase", "--output", out_path, path],
        passphrase,
        write_count=2,  # age prompts: Enter passphrase + Confirm passphrase
    )
    if rc != 0:
        raise RuntimeError(stderr.decode().strip())


def main():
    _check_age()

    to_encrypt = [
        os.path.join(CONFIG_DIR, f)
        for f in SENSITIVE_FILES
        if os.path.isfile(os.path.join(CONFIG_DIR, f))
    ]

    if not to_encrypt:
        print("Nothing to encrypt — no plaintext files found.")
        sys.exit(0)

    print("Will encrypt:")
    for p in to_encrypt:
        print(f"  {os.path.relpath(p, PROJECT_ROOT)}")
    print()

    passphrase = getpass.getpass("Passphrase: ")
    confirm = getpass.getpass("Confirm passphrase: ")
    if passphrase != confirm:
        print("Passphrases do not match.")
        sys.exit(1)
    if not passphrase:
        print("Passphrase cannot be empty.")
        sys.exit(1)

    print()
    encrypted = []
    for path in to_encrypt:
        rel = os.path.relpath(path, PROJECT_ROOT)
        try:
            _encrypt(path, passphrase)
            print(f"  {rel} → {rel}.age")
            encrypted.append(path)
        except RuntimeError as e:
            print(f"  ERROR encrypting {rel}: {e}")
            sys.exit(1)

    print()
    answer = input("Delete plaintext files? [y/N] ").strip().lower()
    if answer == "y":
        for path in encrypted:
            os.remove(path)
            print(f"  Deleted {os.path.relpath(path, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
