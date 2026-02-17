import os
import time
import threading
import sys
import usb.core
import usb.util
import psutil
import uvicorn
from fastapi import FastAPI
from parseArg import extractVersion
from utils import DEV_MODE, SOCKET_PATH, get_build_identity
from models import Fan, SystemStatus, VersionInfo, VersionStatus
from typing import List, Literal
from vars import APP_NAME, APP_RAW_VERSION, APP_RC, APP_VERSION
import httpx 

shared_state: SystemStatus = None

def update_state(temp: int, fans: List[Fan]):
    global shared_state
    shared_state = SystemStatus(
            timestamp=time.time(),
            cpu_temp=temp,
            fans=fans
        )

LATEST_VER: VersionInfo = None
LAST_VER_CHECK = 0.0
LAST_VER_FETCH = 0.0

def fetch_github_tag():
    global LAST_VER_FETCH
    global LATEST_VER
    current_ver = extractVersion(APP_RAW_VERSION)
    repo = "Yoinky3000/LL-Connect-Wireless"
    url = f"https://api.github.com/repos/{repo}/releases"

    TEST_MODE = DEV_MODE and False 
    test_releases = [
        {"tag_name": "v1.2.1-rc9-rel3"},
        {"tag_name": "1.1.0-rel5"},
        {"tag_name": "1.1.0-rc2-rel1"},
    ]

    try:
        if TEST_MODE:
            release_res = test_releases
        else:
            now = time.time()
            if (now - LAST_VER_FETCH) < 75: return
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
                if response.status_code == 200:
                    release_res = response.json()
                else:
                    release_res = None
                LAST_VER_FETCH = time.time()

        if not release_res:
            LATEST_VER = current_ver
            return
        
        releases: List[VersionInfo] = []
        dist, arch, ext = get_build_identity()
        match_pattern = f"{dist}.{arch}{ext}"
        for r in release_res:
            assets = r.get("assets", [])
            installer_url=None 
            for asset in assets:
                if match_pattern in asset["name"]:
                    installer_url = asset["browser_download_url"]
                    break
            releases.append(extractVersion(raw_tag=r["tag_name"].lstrip('v'), release_note=r.get("body", "No release notes provided."), installer_url=installer_url))

        if APP_RC == 0:
            for r in releases:
                if not r.rc:
                    LATEST_VER = r
                    break
        else:
            for r in releases:
                if r.rc == 0:
                    LATEST_VER = r
                    break
                
                if r.semver == APP_VERSION and r.rc > 0:
                    LATEST_VER = r
                    break
        
        if LATEST_VER:
            return True
        else:
            LATEST_VER = current_ver

    except Exception as e:
        print(f"Failed to fetch latest tag: {e}")
        LATEST_VER = current_ver


# ==============================
# SOCK SERVER
# ==============================

app = FastAPI()
@app.get("/status", response_model=SystemStatus)
async def get_status():
    return shared_state

@app.get("/version", response_model=VersionStatus)
async def get_version():
    global LAST_VER_CHECK, LATEST_VER
    fetch_github_tag()
    now = time.time()
    
    new_ver = LATEST_VER.semver > APP_VERSION
    graduation = (LATEST_VER.semver == APP_VERSION and APP_RC > 0 and LATEST_VER.rc == 0)
    new_rc = (LATEST_VER.semver == APP_VERSION and LATEST_VER.rc > APP_RC)
    
    outdated = new_ver or graduation or new_rc
    
    is_stale = (now - LAST_VER_CHECK) > 3600
    
    notified = True
    if outdated:
        if is_stale:
            notified = False
            LAST_VER_CHECK = now
        else:
            notified = True
    else:
        notified = True

    return VersionStatus(
        data=LATEST_VER,
        notified=notified,
        outdated=outdated
    )

@app.get("/")
async def root():
    return {"status": "running", "service": APP_NAME}

def start_api_server():
    uvicorn.run(app, uds=SOCKET_PATH, log_level="warning")


# ==============================
# USB CONSTANTS
# ==============================
VID = 0x0416
TX = 0x8040
RX = 0x8041

USB_OUT = 0x01
USB_IN  = 0x81

GET_DEV_CMD = 0x10
RF_PAGE_STRIDE = 434
MAX_DEVICES_PAGE = 10

# ==============================
# USER CONFIG
# ==============================
MIN_PWM = 20
MAX_PWM = 175

MIN_TEMP = 35.0
MAX_TEMP = 85.0

DAMPING_SECOND = 2.0
DAMPING_TEMP   = 1.0

PWM_STEP = 4
PWM_STEP_INTERVAL = 0.5


LOOP_INTERVAL  = 0.5

# ==============================
# UTILS
# ==============================
def u8(x):
    return bytes([x & 0xFF])

def mac_to_bytes(mac):
    return bytes(int(b, 16) for b in mac.split(":"))

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def clear_console():
    sys.stdout.write("\033[H\033[J")
    sys.stdout.flush()

def displayDetected(fans: List[Fan]):
    print("Detected devices:\n")
    print(f"{'MAC Address':17}  Fans  Channel  RX  Bound")
    print("-" * 50)
    for f in fans:
        print(
            f"{f.mac:17}  "
            f"{f.fan_count:>4}     "
            f"{f.channel:>3}     "
            f"{f.rx_type:>2}   "
            f"{'yes' if f.is_bound else 'no'}"
        )


# ==============================
# USB DEVICE HANDLING
# ==============================
def open_device(pid: Literal[32832]):
    dev = usb.core.find(idVendor=VID, idProduct=pid)
    if dev is None:
        raise RuntimeError(f"Device {pid:04x} not found")
    if dev.is_kernel_driver_active(0):
        try:
            dev.detach_kernel_driver(0)
        except usb.core.USBError as e:
            print(f"Could not detach kernel driver: {e}")
    usb.util.claim_interface(dev, 0)
    return dev

def fetch_page(rx: usb.core.Device, page_count: int):
    cmd = bytearray(64)
    cmd[0] = GET_DEV_CMD
    cmd[1] = page_count & 0xFF

    rx.write(USB_OUT, cmd)

    total_len = RF_PAGE_STRIDE * page_count
    buf = bytearray()

    while len(buf) < total_len:
        try:
            chunk = rx.read(USB_IN, 512, timeout=500)
        except usb.core.USBError as e:
            print(e)
            return bytearray()

        buf.extend(chunk)
        if len(chunk) < 512:
            break

    return buf

def list_fans(rx: usb.core.Device, target_pwm: int):
    payload = fetch_page(rx, 1)
    if not payload or payload is None or payload == b'':
        return []
    count = payload[1]
    fans: List[Fan] = []
    offset = 4

    for _ in range(count):
        record = payload[offset:offset+42]
        offset += 42

        if record[41] != 28:
            continue
            
        mac = ":".join(f"{b:02x}" for b in record[0:6])
        fans.append(
            Fan(
                mac=mac,
                master_mac= ":".join(f"{b:02x}" for b in record[6:12]),
                channel= record[12],
                rx_type= record[13],
                fan_count= record[19] % 10,
                pwm= list(record[36:40])[0],
                rpm= [
                    (record[28] << 8) | record[29],
                    (record[30] << 8) | record[31],
                    (record[32] << 8) | record[33],
                    (record[34] << 8) | record[35],
                ],
                target_pwm= target_pwm,
                is_bound= record[6:12] != b"\x00"*6
            )
        )

    return fans

# ==============================
# CPU TEMP
# ==============================
def get_cpu_temp():
    temps = psutil.sensors_temperatures()
    tctl = None
    values = []

    for _, entries in temps.items():
        for e in entries:
            if e.current is not None:
                if e.label == "Tctl": tctl = e.current
                values.append(e.current)

    return tctl if tctl else (max(values) if values else None)

# ==============================
# TEMP → PWM
# ==============================
def temp_to_pwm(temp):
    t = clamp(temp, MIN_TEMP, MAX_TEMP)
    ratio = (t - MIN_TEMP) / (MAX_TEMP - MIN_TEMP)
    return int(MIN_PWM + ratio * (MAX_PWM - MIN_PWM))

def approach_pwm(current, target, step):
    if current < target:
        return min(current + step, target)
    elif current > target:
        return max(current - step, target)
    return current


# ==============================
# BUILD USB DATA
# ==============================
def build_data(fan: Fan, seq):
    frame = bytearray()
    frame += u8(0x10)
    frame += u8(seq)
    frame += u8(fan.channel)
    frame += u8(fan.rx_type)
    frame += u8(0x12)
    frame += u8(0x10)

    if seq == 0:
        frame += mac_to_bytes(fan.mac)
        frame += mac_to_bytes(fan.master_mac)
        frame += u8(fan.rx_type)
        frame += u8(fan.channel)
        frame += u8(fan.rx_type)
        frame += bytes([fan.pwm] * 4)
    else:
        frame += bytes(6)
        frame += bytes(6)
        frame += bytes(3)
        frame += bytes(4)
    return frame

# ==============================
# MAIN LOOP
# ==============================
def fan_control_loop(rx: usb.core.Device, tx: usb.core.Device):
    last_temp = None
    last_target_update = 0

    last_pwm_step_time = {}
    last_fans_amount = 0;

    err = 0
    while True:
        try:
            now = time.time()
            temp = get_cpu_temp()
            if temp is None:
                time.sleep(1)
                continue

            target_pwm = temp_to_pwm(temp)

            if (
                last_temp is None or
                abs(temp - last_temp) >= DAMPING_TEMP and
                now - last_target_update >= DAMPING_SECOND
            ):
                last_temp = temp
                last_target_update = now
            else:
                target_pwm = temp_to_pwm(last_temp)

            fans = list_fans(rx, target_pwm)

            if (last_fans_amount != 0 and len(fans) == 0): continue
            last_fans_amount = len(fans)

            for f in fans:
                mac = f.mac

                if mac not in last_pwm_step_time:
                    last_pwm_step_time[mac] = 0

                if now - last_pwm_step_time[mac] >= PWM_STEP_INTERVAL:
                    f.pwm = approach_pwm(
                        f.pwm,
                        target_pwm,
                        PWM_STEP
                    )
                    last_pwm_step_time[mac] = now

            for f in fans:
                mac = f.mac

                for i in range(len(fans)):
                    tx.write(USB_OUT, build_data(f, i))
                    update_state(temp, fans)
                time.sleep(0.5)

            if DEV_MODE:
                clear_console()
                displayDetected(fans)
                print(f"\n\nCPU Temp: {temp:.1f} °C\n")
                print(f"{'Fan Address':17} | Fans | Cur % | Tgt % | RPM")
                print("-" * 72)


            for d in fans:
                mac = d.mac

                tgt_pwm = target_pwm

                cur_pct = int(d.pwm / 255 * 100)
                tgt_pct = int(tgt_pwm / 255 * 100)

                rpm = ", ".join(str(r) for r in d.rpm if r > 0)

                print(
                    f"{mac:17} | "
                    f"{d.fan_count:>4} | "
                    f"{cur_pct:>5}% | "
                    f"{tgt_pct:>5}% | "
                    f"{rpm}"
                )
            err = 0
        except:
            if err > 3:
                raise Exception()
            else:
                err += 1
        finally:
            time.sleep(LOOP_INTERVAL)



# ==============================
# ENTRY
# ==============================
if __name__ == "__main__":
    tx = None
    rx = None
    try:
        current_ver = extractVersion(APP_RAW_VERSION)
        print(f"Current Version: {APP_RAW_VERSION}")
        print(f"- SEMVER: {current_ver.semver}")
        print(f"- Release Candidate: {current_ver.rc}")
        print(f"- Build Release: {current_ver.release}")
        res = fetch_github_tag()
        if res:
            print(f"Remote Version Fetched: {LATEST_VER.raw_tag}")
            print(f"- SEMVER: {LATEST_VER.semver}")
            print(f"- Release Candidate: {LATEST_VER.rc}")
            print(f"- Build Release: {LATEST_VER.release}")
        print(f"Start sock server at {SOCKET_PATH}")
        api_thread = threading.Thread(target=start_api_server, daemon=True)
        api_thread.start()

        retries = 0
        while not os.path.exists(SOCKET_PATH) and retries < 50:
            time.sleep(0.2)
            retries += 1
        
        if os.path.exists(SOCKET_PATH):
            try:
                os.chmod(SOCKET_PATH, 0o666)
            except OSError:
                pass

        tx = open_device(TX)
        rx = open_device(RX)

        fans = list_fans(rx, 0)
        displayDetected(fans)

        time.sleep(5 if DEV_MODE else 0)
        
        fan_control_loop(rx, tx)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if tx: usb.util.dispose_resources(tx)
        if rx: usb.util.dispose_resources(rx)
        
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        sys.exit(0)
