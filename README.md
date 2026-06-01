# LL-Connect-Wireless

LL-Connect-Wireless is a **Linux daemon and CLI tool** for controlling **Lian Li Wireless Fans** using direct USB communication with the **Lian Li Wireless Controllers**.<br />
It provides real-time fan speed control, temperature-based PWM curves, and a lightweight CLI for monitoring system state.

This project is designed to run as a **system service** and operate independently of proprietary Windows software.

---

## Background

Recently I have ditched windows and start using fedora as my PC OS, as i have had enough of windows poor performance and optimization.

But one thing that frustrated me is that
my pc is built with Lian Li SL120 V3, which is controlled wirelessly with the usb controller, and there is currently no app that support it, so i try to make one by reverse-engineering the signal sent from L-Connect 3 app with wireshark

> Credit to [OpenUniLink](https://github.com/ealcantara22/OpenUniLink) for the methods to communicate with the wireless controller

---

## ⚠️ Disclaimer

**This project is NOT affiliated with, endorsed by, or supported by Lian Li or any of its products.**

* Lian Li® and related product names are trademarks of their respective owners.
* This project is a **reverse-engineered implementation** intended for Linux users.
* Use at your own risk.

---

## Features

* Direct USB control via `libusb`
* Wireless fan detection and monitoring
* Temperature-based PWM control (CPU + GPU if specified)
* 4-point curve mode with linear interpolation between points
* Immediate fan response to temperature changes
* Runs as a systemd service
* CLI for managing the app and real-time status display

---

## Components

| Component              | Description                        |
| ---------------------- | ---------------------------------- |
| `ll-connect-wirelessd` | Background daemon (system service) |
| `ll-connect-wireless`  | CLI tool for viewing live data     |
| systemd service        | Auto-start on boot                 |
| udev rules             | USB permission handling            |

---

## Installation

### Fedora 42/43

Go to the [Release](https://github.com/Yoinky3000/LL-Connect-Wireless/releases/latest) page<br />
Download the rpm package, and install it with dnf:

```bash
sudo dnf install *.fcXX.x86_64.rpm
```

### Ubuntu 22/24, Debian 12

Go to the [Release](https://github.com/Yoinky3000/LL-Connect-Wireless/releases/latest) page<br />
Download the deb package, and install it with apt:

```bash
sudo apt install *.deb
```

### After installation:

* run `start` command to start the service
* you can also use `enable` command to enable the service so that it will keep running if your computer restarted

### Build and package for Debian/Ubuntu

Install build dependencies:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip dpkg-dev build-essential
```

Build:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./deb/compile.sh
```

Install:

```bash
sudo apt install ./deb/.result/ll-connect-wireless-*.deb
```

Enable and run user service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ll-connect-wireless.service
```

### Build and package for Arch Linux

Install build dependencies:

```bash
sudo pacman -S --needed base-devel python python-pip
```

Build:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./arch/compile.sh
```

Install:

```bash
sudo pacman -U ./arch/.result/ll-connect-wireless-*.pkg.tar.zst
```

Enable and run user service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now ll-connect-wireless.service
```

### Other distro

If you would like to help package this for additional distributions, feel free to open a Pull Request!

---

## Quick Start

After installing and starting the service (`llcw start`), here is the common setup flow.
All commands accept the `llcw` alias shown below or the full `ll-connect-wireless` name.

**1. See your fans and their assigned temp source:**

```bash
llcw monitor          # live view with ID / Src columns (Ctrl+C to exit)
```

**2. Pick a control mode** (`curve` for 4-point curves, `linear` for a 2-point line):

```bash
llcw settings set-mode curve
```

**3. Set your fan curves** (`temp:percent` points, see formats below):

```bash
llcw settings curve set-cpu-curve 50:27,60:37,90:70,95:100
llcw settings curve set-gpu-curve 35:30,60:40,70:60,75:90
# linear mode equivalents:
llcw settings linear set-curve 35:10,80:70
llcw settings linear set-gpu-curve 35:25,75:90
```

**4. Assign which temperature drives each fan group** (defaults to CPU):

```bash
llcw settings set-source 1 gpu       # fan ID 1 follows GPU temp
llcw settings set-source 0,2 mix     # fans 0 and 2 follow max(CPU, GPU)
llcw settings show-sources           # ID / MAC / source table
llcw settings clear-sources all      # reset every fan back to CPU
```

Fan IDs come from the `ID` column in `llcw monitor` / `llcw settings show-sources`.
Changes apply immediately — no restart needed. Run `llcw settings` at any time to print
the full current configuration.

---

## CLI Usage

Full CLI reference can be found here:

[CLI.md](CLI.md)

---

## Configuration

Config file path:

`~/.config/ll-connect-wireless/config.json`

Curve mode defaults:

* `CPU_FAN_CURVE=50:27,60:37,90:70,95:100`
* `GPU_FAN_CURVE=35:30,60:40,70:60,75:90`

Linear mode defaults:

* `CPU_LINEAR=35:10,80:70`
* `GPU_LINEAR=35:25,75:90`

Fan groups can be assigned to different temperature sources:

* **CPU** (default): fan speed based on CPU temperature
* **GPU**: fan speed based on GPU temperature
* **Mix**: fan speed = max of CPU and GPU computed fan speeds

`GPU_MACS` and `MIX_MACS` store the MAC addresses of fan groups assigned to each source.
Use `llcw settings set-source <fan_id> <cpu|gpu|mix>` to assign fans by their monitor ID instead of typing MAC addresses.

Example:

```json
{
    "mode": "curve",
    "CPU_FAN_CURVE": "50:27,60:37,90:70,95:100",
    "GPU_FAN_CURVE": "35:30,60:40,70:60,75:90",
    "GPU_MACS": [
        "58:cc:1e:a7:14:54"
    ],
    "MIX_MACS": []
}
```

Curve format:

* Format: `temp_c:percent,temp_c:percent,temp_c:percent,temp_c:percent`
* Each step is a temperature (Celsius) and fan speed (0-100%).
* Values between steps are linearly interpolated.
* Temperatures at or below the first step use that step's speed.
* Temperatures at or above the last step use that step's speed.

---

## Stat Monitoring

You will see something like this when you run the monitor command:

```
CPU Temp: 52.0 °C
GPU Temp: 48.0 °C

 ID  Fan Address       | Fans | Src | Cur % | Tgt % | RPM
------------------------------------------------------------------------------
  0  58:cc:1e:a7:14:54 |    3 | CPU |   32% |   35% | 712, 708, 710
  1  2e:c1:1e:a7:14:54 |    4 | GPU |   32% |   35% | 703, 701, 699, 705
```

---

## Permissions & Security

* The daemon runs as **non-root**
* USB permissions are managed via udev rules
* CLI access does **not** require root, except for update/uninstall

---

## How It Works

1. Daemon communicates directly with the wireless controller over USB
2. Device state is polled periodically
3. CPU temperature is read from the system
4. GPU temperature is read via `nvidia-smi` (if available)
5. Target PWM is calculated from configured curves
6. Fan groups use their assigned temperature source (CPU, GPU, or mix)
7. Fan speeds are updated immediately based on current temperature mapping
8. State is exposed to the CLI via a Unix socket

---

## Roadmap

Planned features:

* Per-channel custom curves
* GUI frontend

---

## License

MIT License<br/>
See `LICENSE` for details.

---
