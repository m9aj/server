#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/m9aj/server.git"

usage() {
    cat <<EOF
Download the server project from GitHub.

Usage:
  bash github_download.sh [destination] [branch]

Arguments:
  destination   Local directory to clone into (default: server)
  branch        Git branch to checkout (default: main)

Examples:
  bash github_download.sh                        # clone main → ./server
  bash github_download.sh server dev       # clone dev branch
  bash github_download.sh ~/my_install dev       # custom destination + branch
EOF
}

case "${1:-}" in
    help|--help|-h)
        usage
        exit 0
        ;;
esac

DEST="${1:-server}"
BRANCH="${2:-main}"

if ! command -v git &>/dev/null; then
    echo "git not found — installing..."
    sudo pacman -Sy --noconfirm git
fi

if [[ -d "$DEST/.git" ]]; then
    echo "Repo already exists at '$DEST', pulling latest..."
    git -C "$DEST" fetch origin
    git -C "$DEST" checkout "$BRANCH"
    git -C "$DEST" pull origin "$BRANCH"
else
    echo "Cloning $REPO ($BRANCH) → $DEST"
    git clone -b "$BRANCH" "$REPO" "$DEST"
fi

chmod +x "$DEST/install"

echo ""
echo "Ready. To install:"
echo "  cd $DEST && ./install"
