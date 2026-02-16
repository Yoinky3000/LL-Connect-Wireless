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
* Temperature-based PWM control
* Smooth fan speed ramping (damping)
* Runs as a systemd service
* CLI for real-time status display

> [!NOTE]
> Currently the pwm is controlled base on a linear curve from `20 / 255 (7.84%)` PWM at 35°C to `175 / 255 (68.63%)` PWM at 85°C
> 
> Configuration for the curve will be added in the future

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

### Fedora 43

Go to the [Release](https://github.com/Yoinky3000/LL-Connect-Wireless/releases/latest) page<br />
Download the rpm package, and install it with dnf:

```bash
sudo dnf install *.rpm
```

### After installation:

* The service will start automatically
* Fan control begins immediately
* No manual configuration is required

### Other distro

Currently, the focus is on Fedora. If you would like to help package this for other distributions (AUR, .deb, etc.), feel free to open a Pull Request!

---

## CLI Usage

Check service status:

```bash
ll-connect-wireless status
```

Restart the service:

```bash
ll-connect-wireless restart
```

Start the service:

```bash
ll-connect-wireless start
```

Stop the service:

```bash
ll-connect-wireless stop
```

Monitor the stat of the controller:

```bash
ll-connect-wireless (or ll-connect-wireless monitor)
```

> [!NOTE]
> You can also use `llcw` instead of `ll-connect-wireless`

---

## Stat Monitoring

You will see something like this when you run the monitor command:

```
CPU Temp: 52.0 °C

Fan Address       | Fans | Cur % | Tgt % | RPM
--------------------------------------------------------
58:cc:1e:a7:14:54 |    3 |   32% |   35% | 712, 708, 710
2e:c1:1e:a7:14:54 |    4 |   32% |   35% | 703, 701, 699, 705
```

---

## Permissions & Security

* The daemon runs as **non-root**
* USB permissions are managed via udev rules
* CLI access does **not** require root, except for start/stop/restart the service

---

## How It Works

1. Daemon communicates directly with the wireless controller over USB
2. Device state is polled periodically
3. CPU temperature is read from the system
4. Target PWM is calculated
5. Fan speeds ramp smoothly to avoid sudden changes
6. State is exposed to the CLI via a Unix socket

---

## Roadmap

Planned features:

* Custom Curve
* Per-channel custom curves
* GUI frontend (optional)

---

## License

MIT License<br/>
See `LICENSE` for details.

---