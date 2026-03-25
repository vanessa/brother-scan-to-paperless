#!/usr/bin/env python3
"""
brother-scan-to-paperless: A lightweight daemon that listens for Brother
scanner button presses and saves scans directly to a Paperless-ngx
consume folder using scanimage.

Works reliably in LXC containers where the official brscan-skey tool
often fails due to forking/daemon issues.

Requires: brscan4 driver, sane-utils, snmp
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime

__version__ = "1.0.0"

DEFAULT_CONFIG_PATHS = [
    "/etc/brother-scan-to-paperless/config.json",
    os.path.expanduser("~/.config/brother-scan-to-paperless/config.json"),
]

DEFAULT_CONFIG = {
    "printer_ip": "",
    "host_ip": "",
    "listen_port": 54925,
    "consume_dir": "",
    "scanner_device": "brother4:net1;dev0",
    "resolution": 300,
    "source": "FB",
    "size": "A4",
    "format": "tiff",
    "register_interval": 300,
    "scan_timeout": 120,
    "display_name": "Paperless",
    "log_file": "/var/log/brother-scan-to-paperless.log",
}


def log(msg: str, log_file: str | None = None) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_file:
        with open(log_file, "a") as f:
            f.write(line + "\n")


def detect_host_ip() -> str | None:
    """Detect the host IP by opening a UDP socket to a public DNS."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def detect_scanner_device() -> str | None:
    """Try to detect the scanner device name using brsaneconfig4."""
    try:
        result = subprocess.run(
            ["brsaneconfig4", "-q"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("*") and "brother" in line.lower():
                # Extract device name from brsaneconfig4 output
                return "brother4:net1;dev0"
        return None
    except Exception:
        return None


def register_profiles(
    printer_ip: str,
    host_ip: str,
    listen_port: int,
    display_name: str,
    log_file: str | None,
) -> bool:
    """Register scan profiles on the printer via SNMP."""
    oid = ".1.3.6.1.4.1.2435.2.3.9.2.11.1.1.0"
    community = "internal"

    functions = [
        ("IMAGE", 1),
        ("EMAIL", 2),
        ("OCR", 3),
        ("FILE", 5),
    ]

    cmd = ["snmpset", "-v1", "-c", community, printer_ip]
    for func, appnum in functions:
        profile = (
            f'TYPE=BR;BUTTON=SCAN;USER="{display_name}";'
            f"FUNC={func};HOST={host_ip}:{listen_port};"
            f"APPNUM={appnum};DURATION=360;BRID=;"
        )
        cmd.extend([oid, "s", profile])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log("Registered scan profiles on printer", log_file)
            return True
        else:
            log(f"SNMP registration failed: {result.stderr.strip()}", log_file)
            return False
    except Exception as e:
        log(f"SNMP registration error: {e}", log_file)
        return False


def do_scan(config: dict) -> bool:
    """Run scanimage and save to the consume folder."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = config["format"]
    outfile = os.path.join(config["consume_dir"], f"scan_{timestamp}.{ext}")
    log_file = config.get("log_file")

    log(f"Starting scan -> {outfile}", log_file)

    try:
        cmd = [
            "scanimage",
            f"--device-name={config['scanner_device']}",
            f"--resolution={config['resolution']}",
            f"--format={config['format']}",
            f"--output-file={outfile}",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=config["scan_timeout"],
        )

        if (
            result.returncode == 0
            and os.path.exists(outfile)
            and os.path.getsize(outfile) > 0
        ):
            size = os.path.getsize(outfile)
            log(f"Scan complete: {outfile} ({size:,} bytes)", log_file)
            return True
        else:
            log(
                f"Scan failed: exit={result.returncode} stderr={result.stderr.strip()}",
                log_file,
            )
            if os.path.exists(outfile):
                os.remove(outfile)
            return False

    except subprocess.TimeoutExpired:
        log(f"Scan timed out after {config['scan_timeout']}s", log_file)
        if os.path.exists(outfile):
            os.remove(outfile)
        return False
    except Exception as e:
        log(f"Scan error: {e}", log_file)
        return False


def load_config(config_path: str | None = None) -> dict:
    """Load config from file, falling back to defaults."""
    config = DEFAULT_CONFIG.copy()

    paths_to_try = [config_path] if config_path else DEFAULT_CONFIG_PATHS
    for path in paths_to_try:
        if path and os.path.exists(path):
            with open(path) as f:
                user_config = json.load(f)
            config.update(user_config)
            break

    return config


def validate_config(config: dict) -> list[str]:
    """Validate config and return list of error messages."""
    errors = []

    if not config.get("printer_ip"):
        errors.append("printer_ip is required")
    if not config.get("host_ip"):
        detected = detect_host_ip()
        if detected:
            config["host_ip"] = detected
        else:
            errors.append("host_ip is required (auto-detection failed)")
    if not config.get("consume_dir"):
        errors.append("consume_dir is required")
    elif not os.path.isdir(config["consume_dir"]):
        errors.append(f"consume_dir does not exist: {config['consume_dir']}")

    return errors


def check_dependencies() -> list[str]:
    """Check that required commands are available."""
    missing = []
    for cmd in ["scanimage", "snmpset", "brsaneconfig4"]:
        if not any(
            os.access(os.path.join(d, cmd), os.X_OK)
            for d in os.environ.get("PATH", "").split(":")
        ):
            missing.append(cmd)
    return missing


def run_daemon(config: dict) -> None:
    """Main daemon loop."""
    log_file = config.get("log_file")

    log("brother-scan-to-paperless daemon starting", log_file)
    log(f"  Printer:    {config['printer_ip']}", log_file)
    log(f"  Host:       {config['host_ip']}", log_file)
    log(f"  Consume:    {config['consume_dir']}", log_file)
    log(f"  Device:     {config['scanner_device']}", log_file)
    log(f"  Resolution: {config['resolution']} dpi", log_file)
    log(f"  Format:     {config['format']}", log_file)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", config["listen_port"]))
    sock.settimeout(30)

    def shutdown(signum, frame):
        log("Shutting down", log_file)
        sock.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    register_profiles(
        config["printer_ip"],
        config["host_ip"],
        config["listen_port"],
        config["display_name"],
        log_file,
    )
    last_register = time.time()

    log(f"Listening on UDP port {config['listen_port']}", log_file)

    while True:
        if time.time() - last_register > config["register_interval"]:
            register_profiles(
                config["printer_ip"],
                config["host_ip"],
                config["listen_port"],
                config["display_name"],
                log_file,
            )
            last_register = time.time()

        try:
            data, addr = sock.recvfrom(1024)
            msg = data.decode("utf-8", errors="replace")
            log(f"Received from {addr}: {msg[:120]}", log_file)

            if "BUTTON=SCAN" in msg:
                do_scan(config)

        except socket.timeout:
            continue
        except Exception as e:
            log(f"Error: {e}", log_file)
            time.sleep(1)


def cmd_setup(args: argparse.Namespace) -> None:
    """Interactive setup wizard."""
    print("brother-scan-to-paperless setup\n")

    config = DEFAULT_CONFIG.copy()

    detected_ip = detect_host_ip()

    config["printer_ip"] = input("Printer IP address: ").strip()

    default_host = detected_ip or ""
    host = input(f"This machine's IP address [{default_host}]: ").strip()
    config["host_ip"] = host or default_host

    config["consume_dir"] = input("Paperless-ngx consume directory path: ").strip()

    resolution = input(f"Scan resolution in DPI [{config['resolution']}]: ").strip()
    if resolution:
        config["resolution"] = int(resolution)

    name = input(f"Display name on printer [{config['display_name']}]: ").strip()
    if name:
        config["display_name"] = name

    errors = validate_config(config)
    if errors:
        print("\nConfiguration errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    config_dir = "/etc/brother-scan-to-paperless"
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.json")

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nConfig saved to {config_path}")
    print("\nRegister scanner with brscan4:")
    print(
        f"  brsaneconfig4 -a name=BROTHER model=DCP-L2540DW ip={config['printer_ip']}"
    )
    print("\nStart the daemon:")
    print("  systemctl enable --now brother-scan-to-paperless")


def cmd_test(args: argparse.Namespace) -> None:
    """Test scan without the daemon."""
    config = load_config(args.config)
    if args.printer_ip:
        config["printer_ip"] = args.printer_ip
    if args.consume_dir:
        config["consume_dir"] = args.consume_dir

    errors = validate_config(config)
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print("Testing scan...")
    success = do_scan(config)
    if success:
        print("Test scan succeeded!")
    else:
        print("Test scan failed. Check logs.")
        sys.exit(1)


def cmd_run(args: argparse.Namespace) -> None:
    """Run the daemon."""
    config = load_config(args.config)

    # CLI overrides
    if args.printer_ip:
        config["printer_ip"] = args.printer_ip
    if args.host_ip:
        config["host_ip"] = args.host_ip
    if args.consume_dir:
        config["consume_dir"] = args.consume_dir
    if args.resolution:
        config["resolution"] = args.resolution
    if args.display_name:
        config["display_name"] = args.display_name

    missing = check_dependencies()
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install with: apt install sane-utils snmp")
        if "brsaneconfig4" in missing:
            print(
                "Install brscan4 from: "
                "https://support.brother.com/g/b/downloadlist.aspx"
                "?c=us&lang=en&prod=dcpl2540dw_us_as&os=128"
            )
        sys.exit(1)

    errors = validate_config(config)
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        print("\nRun 'brother-scan-to-paperless setup' to configure.")
        sys.exit(1)

    run_daemon(config)


def main():
    parser = argparse.ArgumentParser(
        prog="brother-scan-to-paperless",
        description=(
            "Lightweight daemon that listens for Brother scanner button "
            "presses and saves scans to a Paperless-ngx consume folder."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command")

    # run
    run_parser = subparsers.add_parser("run", help="Run the scan daemon")
    run_parser.add_argument("-c", "--config", help="Path to config file")
    run_parser.add_argument("--printer-ip", help="Printer IP address")
    run_parser.add_argument("--host-ip", help="This machine's IP address")
    run_parser.add_argument("--consume-dir", help="Paperless consume directory")
    run_parser.add_argument("--resolution", type=int, help="Scan resolution (DPI)")
    run_parser.add_argument("--display-name", help="Name shown on printer display")

    # setup
    subparsers.add_parser("setup", help="Interactive setup wizard")

    # test
    test_parser = subparsers.add_parser("test", help="Test a single scan")
    test_parser.add_argument("-c", "--config", help="Path to config file")
    test_parser.add_argument("--printer-ip", help="Printer IP address")
    test_parser.add_argument("--consume-dir", help="Paperless consume directory")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "test":
        cmd_test(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
