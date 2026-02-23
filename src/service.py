import os
import time
import threading
import sys
import subprocess
import usb.core
import usb.util
import psutil
import uvicorn
from fastapi import FastAPI
from parseArg import extractVersion
from utils import DEV_MODE, SOCKET_DIR, SOCKET_PATH, load_settings
from models import CurveMode, Fan, FanMode, LinearMode, SystemStatus
from typing import List, Literal, Optional
from vars import APP_NAME, APP_RAW_VERSION

shared_state: SystemStatus = None


def update_state(cpu_temp: Optional[float], gpu_temp: Optional[float], fans: List[Fan]):
    global shared_state
    shared_state = SystemStatus(
        timestamp=time.time(), cpu_temp=cpu_temp, gpu_temp=gpu_temp, fans=fans
    )


# ==============================
# SOCK SERVER
# ==============================

app = FastAPI()


@app.get("/status", response_model=SystemStatus)
async def get_status():
    return shared_state


@app.post("/reload-settings")
async def reload_settings():
    global SETTINGS
    SETTINGS = load_settings()
    return {"msg": "ok"}


@app.get("/")
async def root():
    return {"status": "running", "service": APP_NAME}


def start_api_server():
    os.makedirs(SOCKET_DIR, exist_ok=True)
    uvicorn.run(app, uds=SOCKET_PATH, log_level="warning")


# ==============================
# USB CONSTANTS
# ==============================
VID = 0x0416
TX = 0x8040
RX = 0x8041

USB_OUT = 0x01
USB_IN = 0x81

GET_DEV_CMD = 0x10
RF_PAGE_STRIDE = 434
MAX_DEVICES_PAGE = 10

# ==============================
# USER CONFIG
# ==============================
# MIN_PWM = 20
# MAX_PWM = 175

# MIN_TEMP = 35.0
# MAX_TEMP = 85.0
SETTINGS = load_settings()

LOOP_INTERVAL = 0.5


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


def list_fans(rx: usb.core.Device, last_fans_data: List[Fan] = []):
    payload = fetch_page(rx, 1)
    if not payload or payload is None or payload == b"":
        return []
    count = payload[1]
    fans: List[Fan] = []
    offset = 4

    for _ in range(count):
        record = payload[offset : offset + 42]
        offset += 42

        if record[41] != 28:
            continue

        mac = ":".join(f"{b:02x}" for b in record[0:6])
        previous_target_pwm = next((d for d in last_fans_data if d.mac == mac), 0)
        fans.append(
            Fan(
                mac=mac,
                master_mac=":".join(f"{b:02x}" for b in record[6:12]),
                channel=record[12],
                rx_type=record[13],
                fan_count=record[19] % 10,
                pwm=list(record[36:40])[0],
                rpm=[
                    (record[28] << 8) | record[29],
                    (record[30] << 8) | record[31],
                    (record[32] << 8) | record[33],
                    (record[34] << 8) | record[35],
                ],
                target_pwm=previous_target_pwm if not previous_target_pwm else previous_target_pwm.target_pwm,
                is_bound=record[6:12] != b"\x00" * 6,
            )
        )

    return fans


# ==============================
# CPU/GPU TEMP
# ==============================
def get_cpu_temp():
    temps = psutil.sensors_temperatures()
    tctl = None
    values = []

    for _, entries in temps.items():
        for e in entries:
            if e.current is not None:
                if e.label == "Tctl":
                    tctl = e.current
                values.append(e.current)

    return tctl if tctl else (max(values) if values else None)


def get_gpu_temp():
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        )
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None

    values: List[float] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    return max(values) if values else None


# ==============================
# TEMP → PWM
# ==============================
def temp_to_pwm(temp: float, linear: LinearMode):
    t = clamp(temp, linear.min_temp, linear.max_temp)

    delta = linear.max_temp - linear.min_temp
    if delta <= 0:
        return int(linear.min_pwm / 100 * 255)

    ratio = (t - linear.min_temp) / delta

    pwm_percent = linear.min_pwm + ratio * (linear.max_pwm - linear.min_pwm)

    pwm_percent = clamp(pwm_percent, 0, 100)

    return int(round(pwm_percent / 100 * 255))


def curve_to_pwm(temp: float, curve: CurveMode):
    points = curve.points

    if temp <= points[0].temp_c:
        return int(round(points[0].percent / 100 * 255))
    if temp >= points[-1].temp_c:
        return int(round(points[-1].percent / 100 * 255))

    for i in range(1, len(points)):
        left = points[i - 1]
        right = points[i]
        if temp <= right.temp_c:
            ratio = (temp - left.temp_c) / (right.temp_c - left.temp_c)
            pwm_percent = left.percent + ratio * (right.percent - left.percent)
            pwm_percent = clamp(pwm_percent, 0, 100)
            return int(round(pwm_percent / 100 * 255))

    return int(round(points[-1].percent / 100 * 255))


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
    global SETTINGS
    last_fans_amount = 0
    warned_missing_gpu_temp = False
    last_fans_data: List[Fan] = []

    err = 0
    while True:
        try:
            cpu_temp = get_cpu_temp()
            gpu_mac_set = set(SETTINGS.gpu_temp_macs)
            should_read_gpu_temp = len(gpu_mac_set) > 0
            gpu_temp = get_gpu_temp() if should_read_gpu_temp else None

            cpu_target_pwm: Optional[int] = None
            gpu_target_pwm: Optional[int] = None

            if SETTINGS.mode == FanMode.linear:
                if cpu_temp is not None:
                    cpu_target_pwm = temp_to_pwm(cpu_temp, SETTINGS.linear)

                if should_read_gpu_temp and gpu_temp is not None:
                    gpu_target_pwm = temp_to_pwm(gpu_temp, SETTINGS.gpu_linear)
                    warned_missing_gpu_temp = False
                elif should_read_gpu_temp and cpu_temp is not None:
                    gpu_target_pwm = temp_to_pwm(cpu_temp, SETTINGS.gpu_linear)
                    if DEV_MODE and not warned_missing_gpu_temp:
                        print(
                            "GPU temp unavailable; GPU-routed fan groups are temporarily using CPU temperature with GPU linear mapping."
                        )
                        warned_missing_gpu_temp = True
                else:
                    warned_missing_gpu_temp = False
            else:
                if cpu_temp is not None:
                    cpu_target_pwm = curve_to_pwm(cpu_temp, SETTINGS.cpu_curve)

                if should_read_gpu_temp and gpu_temp is not None:
                    gpu_target_pwm = curve_to_pwm(gpu_temp, SETTINGS.gpu_curve)
                    warned_missing_gpu_temp = False
                elif should_read_gpu_temp and cpu_temp is not None:
                    gpu_target_pwm = curve_to_pwm(cpu_temp, SETTINGS.cpu_curve)
                    if DEV_MODE and not warned_missing_gpu_temp:
                        print(
                            "GPU temp unavailable; GPU-routed fan groups are temporarily using the CPU curve."
                        )
                        warned_missing_gpu_temp = True
                else:
                    warned_missing_gpu_temp = False

            if cpu_target_pwm is None and gpu_target_pwm is None:
                time.sleep(1)
                continue

            fans = list_fans(rx, last_fans_data)

            if last_fans_amount != 0 and len(fans) == 0:
                continue
            last_fans_amount = len(fans)

            updated_fans: List[str] = []

            for f in fans:
                mac = f.mac.lower()
                wants_gpu_temp = mac in gpu_mac_set
                if wants_gpu_temp and gpu_target_pwm is not None:
                    target_pwm = gpu_target_pwm
                elif cpu_target_pwm is not None:
                    target_pwm = cpu_target_pwm
                else:
                    target_pwm = f.pwm
                if target_pwm != f.target_pwm: updated_fans.append(f.mac)

                f.target_pwm = target_pwm
                f.pwm = f.target_pwm
            for f in fans:
                if not f.mac in updated_fans: continue
                for i in range(len(fans)):
                    tx.write(USB_OUT, build_data(f, i))
                time.sleep(0.1)

            update_state(cpu_temp, gpu_temp, fans)

            if DEV_MODE:
                clear_console()
                displayDetected(fans)
                cpu_text = f"{cpu_temp:.1f} °C" if cpu_temp is not None else "N/A"
                gpu_text = f"{gpu_temp:.1f} °C" if gpu_temp is not None else "N/A"
                print(f"\n\nCPU Temp: {cpu_text}")
                print(f"GPU Temp: {gpu_text}\n")
                print(f"{'Fan Address':17} | Fans | Cur % | Tgt % | RPM")
                print("-" * 72)

                for d in fans:
                    mac = d.mac

                    tgt_pwm = d.target_pwm

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
            last_fans_data = fans
        except Exception as e:
            if err > 3:
                raise e
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
        
        try:
            tx = open_device(TX)
            rx = open_device(RX)
        except Exception as e:
            print("Unable to open lian li wireless controller")
            print(e)
            sys.exit(1)

        fans = list_fans(rx, [])
        displayDetected(fans)

        time.sleep(5 if DEV_MODE else 0)

        fan_control_loop(rx, tx)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if tx:
            usb.util.dispose_resources(tx)
        if rx:
            usb.util.dispose_resources(rx)

        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        sys.exit(0)
