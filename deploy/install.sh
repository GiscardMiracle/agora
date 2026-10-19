#!/usr/bin/env bash
# Idempotent install on Ubuntu. Run from the repo root:  sudo bash deploy/install.sh
set -euo pipefail

DIR=/opt/agora
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }

apt-get update -qq
apt-get install -y -qq git docker.io curl >/dev/null
systemctl enable --now docker

id agora >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash agora
usermod -aG docker agora

if [ "$(realpath .)" != "$DIR" ]; then
    mkdir -p "$DIR"
    cp -a . "$DIR/"
fi
chown -R agora:agora "$DIR"

sudo -iu agora bash -c 'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -iu agora bash -c "cd $DIR && ~/.local/bin/uv sync --frozen 2>/dev/null || ~/.local/bin/uv sync"

docker build -t agora-runner:latest "$DIR/runner"

if [ ! -f "$DIR/.env" ]; then
    cp "$DIR/.env.example" "$DIR/.env"
    sed -i "s/^AGORA_PASSWORD=.*/AGORA_PASSWORD=$(openssl rand -base64 12)/; s/^AGORA_SECRET=.*/AGORA_SECRET=$(openssl rand -hex 32)/" "$DIR/.env"
    chown agora:agora "$DIR/.env"
    chmod 600 "$DIR/.env"
    echo ">> created $DIR/.env (generated password: $(grep ^AGORA_PASSWORD "$DIR/.env" | cut -d= -f2))"
fi

cp "$DIR/deploy/agora.service" /etc/systemd/system/agora.service
systemctl daemon-reload
systemctl enable agora
systemctl restart agora
echo ">> agora running on 127.0.0.1:8080 — put Caddy/nginx in front (see deploy/Caddyfile)"
