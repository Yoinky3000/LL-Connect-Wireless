import sys
import time
import argparse
import subprocess
import httpx
from utils import SOCKET_PATH, SystemStatus, VersionStatus
from vars import APP_VERSION, APP_NAME, APP_ALIAS

def clear_console():
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()

def fetch_state() -> SystemStatus:
    transport = httpx.HTTPTransport(uds=SOCKET_PATH)
    with httpx.Client(transport=transport) as client:
        resp = client.get("http://localhost/status")
        resp.raise_for_status()
        return SystemStatus(**resp.json())

def render(status: SystemStatus):
    clear_console()
    print(f"LLCW CLI (Version: {APP_VERSION})\n\n")

    print(f"CPU Temp: {status.cpu_temp:.1f} °C\n")
    print(f"{'Fan Address':17} | Fans | Cur % | Tgt % | RPM")
    print("-" * 72)

    for f in status.fans:
        cur_pct = int(f.pwm / 255 * 100)
        tgt_pct = int(f.target_pwm / 255 * 100)
        rpm = ", ".join(str(r) for r in f.rpm)

        print(
            f"{f.mac:17} | "
            f"{f.fan_count:>4} | "
            f"{cur_pct:>5}% | "
            f"{tgt_pct:>5}% | "
            f"{rpm}"
        )

def run_monitor():
    try:
        err = 0
        while True:
            try:
                state = fetch_state()
                render(state)
                err = 0
            except Exception as e:
                err += 1
                clear_console()
                print(f"Connection Lost. Retrying... ({err})")
                if err > 5:
                    print(f"\nDaemon might be down. Try: {APP_NAME} status")
                    sys.exit(1)
            time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)

def run_systemctl(action: str):
    service_name = f"{APP_NAME}.service"
    
    try:
        print(f"Running: systemctl {action} {service_name}...")
        subprocess.run(["systemctl", action, service_name], check=False)
        print("Done.")
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        sys.exit(e.returncode)
    except FileNotFoundError:
        print("Error: 'systemctl' command not found. Are you sure you are using in Linux?")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)

def check_update(wait = False):
    try:
        transport = httpx.HTTPTransport(uds=SOCKET_PATH)
        with httpx.Client(transport=transport) as client:
            resp = client.get("http://localhost/version")
            if resp.status_code == 200:
                v_data = VersionStatus(**resp.json())

                if v_data.latest_ver != "unknown" and v_data.latest_ver != APP_VERSION and not v_data.checked:
                    print(f"\n\033[93m[!] UPDATE AVAILABLE: Version {v_data.latest_ver} is out!\033[0m")
                    print(f"Current version: {APP_VERSION}")
                    print("Download: https://github.com/Yoinky3000/LL-Connect-Wireless/releases\n")
                    if wait: time.sleep(5)
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"Linux L-Connect Wireless CLI (Version: {APP_VERSION})",
        epilog=f"You can also use '{APP_NAME}' without arguments to see live monitor.\n\n'{APP_ALIAS}' is also an alias command to '{APP_NAME}'"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("help", help="same as -h/--help")

    subparsers.add_parser("status", help="show systemd service status")

    subparsers.add_parser("start", help="start the background daemon")

    subparsers.add_parser("stop", help="stop the background daemon")

    subparsers.add_parser("restart", help="restart the background daemon")
    
    subparsers.add_parser("monitor", help="show live fan monitor")

    args = parser.parse_args()

    is_monitor = args.command == "monitor" or args.command is None
    check_update(wait=is_monitor)

    if args.command == "help":
        parser.print_help()
    elif args.command == "status":
        run_systemctl("status")
    elif args.command == "start":
        run_systemctl("start")
    elif args.command == "stop":
        run_systemctl("stop")
    elif args.command == "restart":
        run_systemctl("restart")
    elif args.command == "display":
        run_monitor()
    else:
        run_monitor()