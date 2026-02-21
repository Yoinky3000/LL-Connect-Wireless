import sys
import time
import argparse
import subprocess
from typing import Optional
import httpx
from utils import SOCKET_PATH, get_build_identity
from models import SystemStatus, VersionInfo, VersionStatus
from vars import APP_RAW_VERSION, APP_NAME, APP_ALIAS
import shtab

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
    print(f"LL-Connect-Wireless Monitor\n\n")

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

def run_info(remote_ver: Optional[VersionStatus]):
    try:
        print("\033[1mLL-Connect-Wireless Information\033[0m")
        print("-" * 30)
        print(f"\033[1mCURRENT_VERSION:\033[0m {APP_RAW_VERSION}")
        
        if remote_ver:
            v = remote_ver.data
            print(f"\033[1mREMOTE_VERSION:\033[0m  {v.raw_tag}")
            release_note = getattr(v, "release_note", "")
        else: 
            print(f"\033[1mREMOTE_VERSION:\033[0m  Unknown")
            release_note = "You can run 'llcw update' to update to latest version from GitHub."
        print("-" * 30)
        print("\033[1mCHANGE_LOG:\033[0m")
        print(release_note)
        print("-" * 30)
    except Exception as e:
        print(f"Could not connect to daemon: {e}")

def run_update(remote_ver: Optional[VersionStatus]):
    if not remote_ver:
        print("Could not retrieve version information from the daemon.")
        return

    if not remote_ver.outdated:
        print("You are already up to date.")
        return
    
    dist_tag, arch, ext = get_build_identity()
    print(f"\033[1mYour System Info\033[0m -")
    print(f"  Distribution Tag > {dist_tag}")
    print(f"  Architecture > {arch}")
    print(f"  Installer Extension > {ext}\n")
    
    url = remote_ver.data.installer_url
    if not url:
        print("\033[91mNo compatible installer found for your specific system architecture/distro.\033[0m")
        return

    tmp_path = f"/tmp/llcw_update{ext}"

    print(f"\n\033[1mUpdate Found: {remote_ver.data.raw_tag}\033[0m")
    print(f"Download URL: {url}")
    print(f"Target Path:  {tmp_path}")
    print("-" * 40)

    confirm = input("Do you want to proceed with the download and installation? (y/N): ").lower()
    if confirm != 'y':
        print("Update cancelled.")
        return

    print(f"\nDownloading {url}...")
    try:
        with httpx.Client(follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        
        print("Download complete. Starting installation...")
        
        if ext == ".rpm":
            subprocess.run(["sudo", "dnf", "install", "-y", tmp_path], check=True)
        elif ext == ".deb":
            subprocess.run(["sudo", "apt", "install", "-y", tmp_path], check=True)
        else:
            print(f"\033[93mAutomatic installation not supported for {ext}.\033[0m")
            print(f"Please install the file manually from: {tmp_path}")
            return
        print("\033[92mLL-Connect-Wireless updated successfully!\033[0m")

    except httpx.HTTPError as e:
        print(f"\033[91mDownload failed: {e}\033[0m")
    except subprocess.CalledProcessError as e:
        print(f"\033[91mInstallation failed: {e}\033[0m")
    except Exception as e:
        print(f"\033[91mAn unexpected error occurred: {e}\033[0m")

def check_update() -> Optional[VersionStatus]:
    try:
        transport = httpx.HTTPTransport(uds=SOCKET_PATH)
        with httpx.Client(transport=transport) as client:
            resp = client.get("http://localhost/version")
            if resp.status_code == 200:
                remoteVer = VersionStatus(**resp.json())
                return remoteVer
            return None
    except Exception:
        return None

def printOutdated(newVer: VersionInfo, wait = False):
    display = newVer.semver
    if newVer.rc:
        display += f" (RC{newVer.rc})"
    print(f"\n\033[93m[!] UPDATE AVAILABLE: Version {display} is out!\033[0m")
    print(f"Current version: {APP_RAW_VERSION}")
    print(f"Run 'llcw update' to update")
    print(f"Or you can download from: https://github.com/Yoinky3000/LL-Connect-Wireless/releases/tag/{newVer.raw_tag}\n")
    if wait: 
        time.sleep(5)

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(
            description=f"LL-Connect-Wireless (LLCW) CLI (Version: {APP_RAW_VERSION})",
            epilog=f"You can also use '{APP_NAME}' without arguments to see live monitor.\n\n'{APP_ALIAS}' is also an alias command to '{APP_NAME}'"
        )
        
        subparsers = parser.add_subparsers(dest="command", help="Available commands")

        subparsers.add_parser("help", help="same as -h/--help")

        subparsers.add_parser("info", help="show app version info and changelog of llcw")

        subparsers.add_parser("update", help="check and update llcw to latest version")

        subparsers.add_parser("status", help="show systemd service status")

        subparsers.add_parser("start", help="start the background daemon")

        subparsers.add_parser("stop", help="stop the background daemon")

        subparsers.add_parser("restart", help="restart the background daemon")
        
        subparsers.add_parser("monitor", help="show live fan monitor (Default to it if no command is provided)")

        parser.add_argument(
            "--print-completion",
            choices=shtab.SUPPORTED_SHELLS,
            help="print shell completion script",
        )

        args = parser.parse_args()

        if args.print_completion:
            print(shtab.complete(parser, shell=args.print_completion))
            sys.exit(0)

        is_monitor = args.command == "monitor" or args.command is None
        remoteVer = check_update()
        if (remoteVer and remoteVer.outdated and not remoteVer.notified and not args.command == "info" and not args.command == "update"):
            printOutdated(remoteVer.data, is_monitor)

        if is_monitor:
            run_monitor()
        elif args.command == "info":
            run_info(remoteVer)
        elif args.command == "update":
            run_update(remoteVer)
        elif args.command == "status":
            run_systemctl("status")
        elif args.command == "start":
            run_systemctl("start")
        elif args.command == "stop":
            run_systemctl("stop")
        elif args.command == "restart":
            run_systemctl("restart")
        else:
            parser.print_help()
    except KeyboardInterrupt:
        sys.exit(0)