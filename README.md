```markdown
# Karukera Telemetry Hub: RaceBox Micro GPS & IMU Streaming

A high-performance, real-time data bridge and analytics dashboard designed to stream high-frequency (25Hz) binary data from a **RaceBox Micro** over Bluetooth Low Energy (BLE) to an interactive local web interface. Optimized for marine deployment, it features live 3D attitude estimation, wave height ledger tracking, rolling G-force/gyro graphs, and automated CSV logging.

---

## 🏗️ Hardware & System Requirements

* **Vessel Computer:** Raspberry Pi 4 / Pi 5 running Raspberry Pi OS.
* **Sensor Hardware:** RaceBox Micro (configured via BLE UART).
* **Network:** Access via local network (Ethernet/Wi-Fi router on the boat).

---

## 🔌 Core Dependencies

### 1. Linux System Packages
The underlying BLE communication engine relies on the Linux Bluetooth architecture (`bluez`).
```bash
sudo apt update
sudo apt install bluetooth bluez libglib2.0-dev -y

```

### 2. Python Packages (Virtual Environment)

The application handles asynchronous high-frequency tasks, raw binary decoding, and modern WebSocket streaming using the following core packages:

* `fastapi` & `uvicorn` (with `websockets` support) — High-throughput telemetry server.
* `bleak` — Asynchronous Bluetooth Low Energy client wrapper.

---

## 🚀 Step-by-Step Deployment Guide

### Step 1: Initialize the Python Environment

Clone your repository, create your virtual environment, and install the necessary dependencies:

```bash
cd ~/racebox_gps_imu_streaming

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install application dependencies
pip install fastapi uvicorn bleak websockets

```

### Step 2: Initialize & Configure Raspberry Pi Bluetooth

On a fresh Raspberry Pi OS install, the Bluetooth chip is often software-blocked by default and lacks user permissions. Run these commands to wake up the radio:

```bash
# 1. Unblock the Bluetooth RF chip
sudo rfkill unblock bluetooth

# 2. Power up the local Bluetooth controller antenna
sudo bluetoothctl power on

# 3. Grant Python raw socket capabilities (Crucial for running without 'sudo' in venv)
sudo setcap 'cap_net_raw,cap_net_admin=eip' $(readlink -f $(which python3))

```

#### Quick Bluetooth Sanity Check

Verify the Pi can physically see the RaceBox Micro broadcasts before spinning up the API pipeline:

```bash
bluetoothctl scan on

```

*(Look for your device address, e.g., `[NEW] Device AA:BB:CC:DD:EE:FF RaceBox Micro`. Press `CTRL+C` to cancel the scanner).*

### Step 3: Run the Telemetry Hub

With your virtual environment active and Bluetooth unblocked, run the streaming application:

```bash
python3 racebox_stream.py

```

---

## 🗺️ Accessing the Dashboard

The application binds directly to host `0.0.0.0` on port `8000`. This allows any tablet, smartphone, or navigation screen connected to your vessel's onboard local network to view the interface.

* **Local Access (On the Pi):** `http://127.0.0.1:8000`
* **Network Access (On Deck):** `http://<your-raspberry-pi-ip>:8000`

---

## 📊 Features & Operations

* **3D Horizon Space:** Real-time canvas orientation displaying vessel Heel (Roll) and Trim (Pitch).
* **Wave Rolling Ledger:** Tracks and categorizes the last 10 wave cycles, assessing structural height, wave period, and vertical slamming forces ($G$).
* **Set Neutral Tare:** Instantly re-zeroes internal sensor offsets based on current orientation parameters (use when floating flat in calm water).
* **Dock Mode (Eco):** Throttles telemetry capture down to 1Hz parsing frequency to dramatically limit processing overhead and protect long-term vessel battery state while moored.
* **Automated Log Rollover:** Writes standard raw rows down to automated hour-incremented CSV ledgers (`racebox_log_YYYY-MM-DD-HH.csv`) for post-voyage velocity prediction modeling.

```

```
