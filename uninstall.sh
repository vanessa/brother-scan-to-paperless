#!/usr/bin/env bash
set -euo pipefail

# brother-scan-to-paperless uninstaller

INSTALL_DIR="/opt/brother-scan-to-paperless"
BIN_LINK="/usr/local/bin/brother-scan-to-paperless"
SERVICE_FILE="/etc/systemd/system/brother-scan-to-paperless.service"
CONFIG_DIR="/etc/brother-scan-to-paperless"
LOG_FILE="/var/log/brother-scan-to-paperless.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

[[ $EUID -ne 0 ]] && { echo -e "${RED}[ERROR]${NC} Must be run as root"; exit 1; }

# Stop and disable service
if systemctl is-active --quiet brother-scan-to-paperless 2>/dev/null; then
    info "Stopping service..."
    systemctl stop brother-scan-to-paperless
fi
if systemctl is-enabled --quiet brother-scan-to-paperless 2>/dev/null; then
    info "Disabling service..."
    systemctl disable brother-scan-to-paperless
fi

# Remove files
[[ -f "$SERVICE_FILE" ]] && rm -f "$SERVICE_FILE" && info "Removed $SERVICE_FILE"
[[ -L "$BIN_LINK" ]]     && rm -f "$BIN_LINK"     && info "Removed $BIN_LINK"
[[ -d "$INSTALL_DIR" ]]  && rm -rf "$INSTALL_DIR"  && info "Removed $INSTALL_DIR"

systemctl daemon-reload

echo ""
info "Uninstalled successfully."
echo ""

if [[ -d "$CONFIG_DIR" ]]; then
    warn "Config preserved at $CONFIG_DIR (remove manually if desired)"
fi
if [[ -f "$LOG_FILE" ]]; then
    warn "Log preserved at $LOG_FILE (remove manually if desired)"
fi
