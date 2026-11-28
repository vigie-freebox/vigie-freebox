#!/bin/bash
# Installe (ou met à jour) la version serveur de Vigie Freebox sur Debian / Ubuntu / Raspberry Pi OS.
#   sudo bash install.sh
# Utilisé automatiquement par l'assistant « surveillance permanente » (VM de la Freebox).
set -euo pipefail
DEST=/opt/vigie-freebox
DATA=/var/lib/vigie-freebox
REPO=https://github.com/vigie-freebox/vigie-freebox

if [ "$(id -u)" -ne 0 ]; then echo "Lancez ce script avec sudo."; exit 1; fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv git fonts-dejavu-core

if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only -q || true
elif [ ! -f "$DEST/vigie/server.py" ]; then
  git clone --depth 1 "$REPO" "$DEST"
fi

id vigie >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin vigie
mkdir -p "$DATA/rapports"
chown -R vigie:vigie "$DATA"
chmod 700 "$DATA"

python3 -m venv "$DEST/venv"
"$DEST/venv/bin/pip" install -q --upgrade pip
"$DEST/venv/bin/pip" install -q "requests>=2.31" "reportlab>=4.0"

install -m 644 "$DEST/serveur/vigie-freebox.service" /etc/systemd/system/vigie-freebox.service
systemctl daemon-reload
systemctl enable --now vigie-freebox
systemctl restart vigie-freebox

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "Vigie Freebox est installé : http://${IP:-adresse-de-cette-machine}:8099/"
