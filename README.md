# brother-scan-to-paperless

A lightweight daemon that turns your Brother scanner's Scan button into a one-press pipeline to [Paperless-ngx](https://docs.paperless-ngx.com/).

Press Scan on your Brother printer → document lands in Paperless.

> Important: This is a personal project that works on my specific setup. It's not a polished, general-purpose tool. You're welcome to use it, open a PR, fork it, or learn from it, but expect to read the code and adapt things to your environment. No guarantees it'll work out of the box for you.

## Why this exists

Brother provides `brscan-skey` as their official Linux scan-button tool, but it's unreliable in headless and containerized environments (LXC, Docker). It forks unpredictably, drops connections, and fights with systemd  - making it nearly unusable on a home server.

This daemon replaces `brscan-skey` with ~300 lines of Python that:

- Registers scan profiles on the printer via SNMP (so your server appears as a scan destination)
- Listens for button-press events on UDP port 54925
- Runs `scanimage` (which works perfectly) to capture the scan
- Drops the file directly into Paperless-ngx's consume folder

It's been tested on Proxmox LXC containers running Debian, but should work anywhere Linux runs.

## Requirements

- **Brother scanner** with network scanning (tested with DCP-L2540DW; should work with most networked Brother MFPs)
- **brscan4** driver from Brother ([download page](https://support.brother.com))
- **Python 3.10+**
- **sane-utils** (provides `scanimage`)
- **snmp** (provides `snmpset` for printer registration)

## Important

This daemon must run on the **same machine** as Paperless-ngx - it saves scans directly to the local consume folder. Running the daemon on a separate machine from Paperless is not currently supported. PRs to add support for remote/networked consume directories are welcome.

## Installation

```bash
git clone https://github.com/vanessa/brother-scan-to-paperless.git
cd brother-scan-to-paperless
sudo bash install.sh
```

The installer will:

- Install system dependencies (`sane-utils`, `snmp`)
- Check for the `brscan4` driver
- Install the daemon to `/opt/brother-scan-to-paperless/`
- Set up a systemd service

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/vanessa/brother-scan-to-paperless.git ~/brother-scan-to-paperless
cd ~/brother-scan-to-paperless
```

### 2. Install the Brother scanner driver

Download the **Scanner driver 64bit (deb package)** for your model from [Brother's support site](https://support.brother.com):

```bash
wget https://download.brother.com/welcome/dlf105200/brscan4-0.4.11-1.amd64.deb
sudo dpkg -i --force-all brscan4-0.4.11-1.amd64.deb
```

If `/etc/sane.d/` doesn't exist (common in LXC containers):

```bash
sudo mkdir -p /etc/sane.d
echo "brother4" | sudo tee /etc/sane.d/dll.conf
```

### 3. Register your scanner

```bash
sudo brsaneconfig4 -a name=BROTHER model=DCP-L2540DW ip=YOUR_PRINTER_IP
```

Replace `DCP-L2540DW` with your model and `YOUR_PRINTER_IP` with the printer's IP address. Verify with:

```bash
brsaneconfig4 -q | grep BROTHER
```

### 4. Run the setup wizard

```bash
sudo brother-scan-to-paperless setup
```

This will ask for:

- **Printer IP**  - your Brother scanner's IP address
- **Host IP**  - the IP of the machine running this daemon (auto-detected)
- **Consume directory**  - path to your Paperless-ngx consume folder (e.g., `/mnt/documents/consume`)
- **Resolution**  - scan DPI (default: 300, good for OCR)
- **Display name**  - what appears on the printer's LCD when selecting a scan destination

### 5. Test

```bash
sudo brother-scan-to-paperless test
```

This runs a single scan without the daemon. Place a document on the flatbed first.

### 6. Start the daemon

```bash
sudo systemctl enable --now brother-scan-to-paperless
```

## Usage

Once running, the daemon registers itself with your Brother printer. On the printer's LCD:

1. Press **Scan**
2. Select **Scan to PC** → your display name (e.g., "Paperless")
3. Choose **File** (or Image  - all options trigger a scan)
4. The document is scanned and saved to your consume folder

Paperless-ngx picks it up automatically, runs OCR, and indexes it.

## Configuration

Config lives at `/etc/brother-scan-to-paperless/config.json`:

| Field | Description | Default |
|---|---|---|
| `printer_ip` | Brother printer's IP address | (required) |
| `host_ip` | IP of the machine running the daemon | (auto-detected) |
| `listen_port` | UDP port for scan button events | `54925` |
| `consume_dir` | Paperless-ngx consume folder path | (required) |
| `scanner_device` | SANE device name | `brother4:net1;dev0` |
| `resolution` | Scan resolution in DPI | `300` |
| `source` | Scan source (`FB` = flatbed, `ADF` = feeder) | `FB` |
| `size` | Paper size | `A4` |
| `format` | Output format (`tiff`, `png`, `pnm`) | `tiff` |
| `register_interval` | Seconds between SNMP re-registrations | `300` |
| `scan_timeout` | Max seconds for a single scan | `120` |
| `display_name` | Name shown on printer LCD | `Paperless` |
| `log_file` | Log file path | `/var/log/brother-scan-to-paperless.log` |

All settings can also be passed as CLI flags (run `brother-scan-to-paperless run --help`).

## Logs

```bash
# Live logs via journald
journalctl -u brother-scan-to-paperless -f

# Or the log file
tail -f /var/log/brother-scan-to-paperless.log
```

## Troubleshooting

1. Printer shows "Connecting..." and times out

   - Check the daemon is running: `systemctl status brother-scan-to-paperless`
   - Verify UDP port is open: `ss -ulnp | grep 54925`
   - Test that `scanimage` works directly: `scanimage --device-name="brother4:net1;dev0" --resolution 300 --format=tiff > /tmp/test.tiff`

2. Scanner not found

   - Re-register: `brsaneconfig4 -a name=BROTHER model=YOUR_MODEL ip=PRINTER_IP`
   - Verify: `brsaneconfig4 -q`
   - Ensure `/etc/sane.d/dll.conf` contains `brother4`

3. Scan completes but Paperless doesn't process it

   - Check Paperless worker: `systemctl status paperless-task-queue`
   - Verify file permissions on the consume directory
   - Check Paperless logs for errors

## Uninstall

```bash
sudo bash uninstall.sh
```

This stops the service and removes installed files. Config and logs are preserved.

## How it works

```
                     ┌──────────────┐
                     │   Brother    │
                     │   Printer    │
                     └──────┬───────┘
                            │
              1. SNMP registration
              2. UDP scan button event
              3. TCP scan data (scanimage)
                            │
                     ┌──────▼───────┐
                     │   Daemon     │
                     │  (Python)    │
                     └──────┬───────┘
                            │
                     saves .tiff to
                            │
                     ┌──────▼───────┐
                     │ Paperless-ngx│
                     │  (consume/)  │
                     └──────────────┘
```

1. On startup (and every 5 minutes), the daemon registers scan profiles on the printer via SNMP. This is how the printer knows where to send scan button events.
2. When you press Scan on the printer, it sends a UDP packet to port 54925.
3. The daemon receives the event and runs `scanimage` to pull the scan data from the printer over TCP (port 54921).
4. The resulting TIFF file is saved to Paperless-ngx's consume directory, where it's automatically OCR'd and indexed.

## Tested on

- Brother DCP-L2540DW
- Proxmox LXC (Debian 12/13)
- Paperless-ngx (native install via community script)

If you've tested on other models or setups, please open an issue or PR to add it to the list.

## License

MIT  - see [LICENSE](LICENSE).
