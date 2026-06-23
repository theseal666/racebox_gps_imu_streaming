I have processed the repository context from `https://github.com/theseal666/racebox_gps_imu_streaming/`. Here is the final, fully optimized, and complete `README.md` file reflecting your bare-metal setup, the exact repository naming, the updated `0x00` internal memory blocking fix, and the mathematical physics documentation.

```markdown
# Karukera Telemetry Hub: RaceBox Micro GPS & IMU Streaming

A high-performance, real-time data bridge and analytics dashboard designed to stream high-frequency (25Hz) binary data from a **RaceBox Micro** over Bluetooth Low Energy (BLE) to an interactive local web interface. Optimized for marine deployment, it features live 3D attitude estimation, wave height ledger tracking, rolling G-force/gyro graphs, and automated CSV logging.

---

## 🏗️ Hardware & System Requirements

* **Vessel Computer:** Raspberry Pi 4 / Pi 5 running bare-metal Raspberry Pi OS (Debian-based).
* **Sensor Hardware:** RaceBox Micro (configured via BLE UART).
* **Network:** Access via local network (Ethernet/Wi-Fi router on the boat).

---

## 🔌 Core Dependencies & OS Architecture

The application handles asynchronous high-frequency tasks, raw binary decoding, and modern WebSocket streaming using a split layer of Linux system services and a Python virtual environment.

### 1. Linux System Packages
The underlying BLE communication engine (`bleak`) relies on the Linux Bluetooth architecture (`bluez`) and GLib object libraries.
```bash
sudo apt update
sudo apt install bluetooth bluez libglib2.0-dev -y

```

### 2. Python Environment Architecture

* `fastapi` & `uvicorn` — High-throughput telemetry server utilizing `websockets` for full-duplex data pushes.
* `bleak` — Asynchronous Bluetooth Low Energy client wrapper interacting with the BlueZ system D-Bus.

---

## 🚀 Maintenance & Deployment Guide (Bare-Metal)

### First-Time Setup

If configuring a clean bare-metal environment, clone the repository directly and initialize the Python isolated framework:

```bash
cd ~
git clone [https://github.com/theseal666/racebox_gps_imu_streaming.git](https://github.com/theseal666/racebox_gps_imu_streaming.git)
cd racebox_gps_imu_streaming

# Create an isolated environment to prevent conflicts with system packages
python3 -m venv venv
source venv/bin/activate

# Install core packages
pip install fastapi uvicorn bleak websockets

```

### Update Workflow (Git Pull & Sync)

When updates are pushed to the repository (such as payload adjustments or internal recording overrides), use this streamlined execution sequence to update the bare-metal environment:

```bash
# 1. Navigate to the working path
cd ~/racebox_gps_imu_streaming

# 2. Pull the latest source code adjustments
git pull origin main

# 3. Enter the environment and verify dependency alignment
source venv/bin/activate
pip install --upgrade fastapi uvicorn bleak websockets

# 4. Fire up the data pipeline
python3 racebox_stream.py

```

### 🔧 Crucial Linux Bluetooth Boot Steps

On a bare-metal Raspberry Pi OS installation, the hardware radio chip is often software-blocked by default on startup. Run these commands to wake up the radio controller and grant non-root script execution privileges:

```bash
# 1. Unblock the physical RF chip interface
sudo rfkill unblock bluetooth

# 2. Power up the local Bluetooth controller antenna
sudo bluetoothctl power on

# 3. Grant Python raw socket capabilities (Crucial for running inside venv without 'sudo')
sudo setcap 'cap_net_raw,cap_net_admin=eip' $(readlink -f $(which python3))

```

> **Verification Step:** To ensure the Pi can physically see the hardware broadcasts before initializing the API pipeline, execute `bluetoothctl scan on`. Look for your device address (e.g., `[NEW] Device AA:BB:CC:DD:EE:FF RaceBox Micro`).

---

## 🗺️ Accessing the Dashboard

The application binds directly to host network bridge `0.0.0.0` on port `8000`. This allows any tablet, smartphone, or navigation screen connected to your vessel's onboard local network to view the interface.

* **Local Access (On the Pi):** `http://127.0.0.1:8000`
* **Network Access (On Deck):** `http://<your-raspberry-pi-ip>:8000`

---

## 📊 Sensor Physics, Kinematics & Hydrodynamics

The core logic processes raw metrics at 25Hz to estimate vessel motion. The mechanics behind these calculations are detailed below:

### 1. 3D Orientation (Heel & Trim Estimation)

The vessel's static and dynamic angles are extracted from the 3D accelerometer matrix using trigonometric relationships:

$$\text{Pitch (Trim)} = \theta = \arctan\left(\frac{-A_x}{\sqrt{A_y^2 + A_z^2} + \epsilon}\right)$$

$$\text{Roll (Heel)} = \phi = \arctan\left(\frac{A_y}{A_z}\right)$$

* Where $A_x$, $A_y$, and $A_z$ represent acceleration forces along the device's localized Cartesian frame, and $\epsilon = 0.0001$ protects against zero-division anomalies.
* The local framework is adjustable via the **Set Neutral Tare** function, which caches baseline angular configurations ($\phi_{\text{offset}}$, $\theta_{\text{offset}}$) when floating flat in calm conditions to normalize structural variances.

### 2. Gravity Correction & Vertical Acceleration Isolation

To compute true marine heave and vertical displacement, the algorithm extracts the raw Earth gravity vector ($1.0\text{ G}$) out of the accelerometer matrix. The localized dynamic vector is projected globally:

$$A_{z,\text{true}} = (A_x \cdot \sin\theta) - (A_y \cdot \sin\phi \cdot \cos\theta) + (A_z \cdot \cos\phi \cdot \cos\theta)$$

The system filters out static gravity to compute pure vertical motion relative to the water surface:

$$\text{Motion } Z = A_{z,\text{true}} - 1.0\text{ G} - Z_{\text{offset}}$$

### 3. Dynamic Wave Height Harvesting & Ledger Calculations

The software uses a threshold-bounded double-integration state machine to track passing swells:

* **Trigger Window:** A wave event initiates when vertical motion exceeds a specific threshold ($\text{Motion } Z > 0.08\text{ G}$). The program switches to a `climbing` state and starts an internal timer.
* **Peak Tracking:** The system monitors the peak vertical acceleration ($a_{\text{peak}}$) and lateral structural forces ($A_y$, recorded as structural slamming impact).
* **Integration Loop:** When the vessel drops past the wave crest and transitions into the trough ($\text{Motion } Z < -0.05\text{ G}$), the tracking window ends. The elapsed duration determines the wave period ($t$).

Assuming an approximately sinusoidal vertical velocity profile during the half-period, the localized displacement height ($H$) is calculated using standard kinematic expressions:

$$H = \frac{1}{2} \cdot (a_{\text{peak}} \cdot g) \cdot \left(\frac{t}{2}\right)^2$$

* Where $g = 9.81 \text{ m/s}^2$.
* The result is bounded between $0.1\text{m}$ and $6.5\text{m}$ to filter out high-frequency engine vibration or anomalous sensor drops.

### 4. Wave Steepness Classifications

The physical geometry of the tracked wave is classified by its height-to-period steepness ratio ($S = \frac{H}{t}$):

* $S > 0.6 \rightarrow$ **STEEP / WALL:** Narrow, breaking, or dangerous overtaking seas.
* $S > 0.3 \rightarrow$ **MODERATE:** Standard wind-driven waves.
* $S \le 0.3 \rightarrow$ **LONG SWELL:** Smooth, deep-water ground swell.

```

```
