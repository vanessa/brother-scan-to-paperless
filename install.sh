#!/usr/bin/env bash
set -euo pipefail

# brother-scan-to-paperless installer

INSTALL_DIR="/opt/brother-scan-to-paperless"
BIN_LINK="/usr/local/bin/brother-scan-to-paperless"
SERVICE_FILE="/etc/systemd/system/brother-scan-to-paperless.service"
CONFIG_DIR="/etc/brother-scan-to-paperless"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# Check root
[[ $EUID -ne 0 ]] && error "This script must be run as root"

# Check Python 3.10+
if ! command -v python3 &>/dev/null; then
    error "Python 3 is required. Install with: apt install python3"
fi

PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYMAJOR=$(echo "$PYVER" | cut -d. -f1)
PYMINOR=$(echo "$PYVER" | cut -d. -f2)
if [[ "$PYMAJOR" -lt 3 ]] || { [[ "$PYMAJOR" -eq 3 ]] && [[ "$PYMINOR" -lt 10 ]]; }; then
    error "Python 3.10+ required (found $PYVER)"
fi

info "Installing dependencies..."
apt-get update -qq
apt-get install -y -qq sane-utils snmp > /dev/null 2>&1

# Check for brscan4
if ! command -v brsaneconfig4 &>/dev/null; then
    warn "brscan4 driver not found."
    echo ""
    echo "  Download the 64-bit scanner driver (.deb) for your model from:"
    echo "  https://support.brother.com"
    echo ""
    echo "  Then install with:"
    echo "    dpkg -i --force-all brscan4-*.amd64.deb"
    echo ""
    echo "  After installing, re-run this installer."
    exit 1
fi

# Create sane config dir if missing (common in LXC containers)
if [[ ! -d /etc/sane.d ]]; then
    mkdir -p /etc/sane.d
    echo "brother4" > /etc/sane.d/dll.conf
    info "Created /etc/sane.d/dll.conf"
fi

# Ensure brother4 is in dll.conf
if ! grep -q "brother4" /etc/sane.d/dll.conf 2>/dev/null; then
    echo "brother4" >> /etc/sane.d/dll.conf
    info "Added brother4 to /etc/sane.d/dll.conf"
fi

# Install the daemon
info "Installing daemon to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"
cp src/brother_scan_daemon.py "$INSTALL_DIR/brother_scan_daemon.py"
chmod +x "$INSTALL_DIR/brother_scan_daemon.py"

# Create symlink
ln -sf "$INSTALL_DIR/brother_scan_daemon.py" "$BIN_LINK"
info "Created symlink: $BIN_LINK"

# Install systemd service
info "Installing systemd service..."
cat > "$SERVICE_FILE" << 'EOF'
[Unit]
Description=Brother Scan to Paperless-ngx Daemon
Documentation=https://github.com/vanessa/brother-scan-to-paperless
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/brother-scan-to-paperless run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
info "Systemd service installed"

# Create config dir
mkdir -p "$CONFIG_DIR"

echo ""
info "Installation complete!"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Register your scanner:"
echo "     brsaneconfig4 -a name=BROTHER model=YOUR_MODEL ip=PRINTER_IP"
echo ""
echo "  2. Run the setup wizard:"
echo "     brother-scan-to-paperless setup"
echo ""
echo "  3. Test a scan:"
echo "     brother-scan-to-paperless test"
echo ""
echo "  4. Enable and start the daemon:"
echo "     systemctl enable --now brother-scan-to-paperless"
echo ""
