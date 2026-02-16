import os
import time
import threading
import sys
import usb.core
import usb.util
import psutil
import uvicorn
from fastapi import FastAPI
from utils import DEV_MODE, SOCKET_PATH, Fan, SystemStatus, VersionStatus
from typing import List, Literal
from vars import APP_NAME

shared_state: SystemStatus = None

def update_state(temp: int, fans: List[Fan]):
    global shared_state
    shared_state = SystemStatus(
            timestamp=time.time(),
            cpu_temp=temp,
            fans=fans
        )


LATEST_VER = None
LAST_VER_CHECK = 0.0

def fetch_github_tag():
    global LATEST_VER
    repo = "Yoinky3000/LL-Connect-Wireless"
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        import httpx 
        with httpx.Client(timeout=5.0) as client:
            response = client.get(url)
            if response.status_code == 200:
                LATEST_VER = response.json()["tag_name"].lstrip('v')
                print(f"Latest Version Fetched: {LATEST_VER}")
    except Exception as e:
        print(f"Failed to fetch latest tag: {e}")


# ==============================
# SOCK SERVER
# ==============================

app = FastAPI()
@app.get("/status", response_model=SystemStatus)
async def get_status():
    return shared_state

@app.get("/version", response_model=VersionStatus)
async def get_version():
    global LAST_VER_CHECK
    now = time.time()
    checked = (now - LAST_VER_CHECK) <= 3600
    response = VersionStatus(latest_ver=LATEST_VER, checked=checked)
    if not checked:
        LAST_VER_CHECK = now
    return response

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
        fetch_github_tag()
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

        time.sleep(1)
        
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
