# Karukera Telemetry Hub

Karukera Telemetry Hub is a high-performance marine telemetry pipeline engineered for Raspberry Pi. It connects to a **RaceBox Micro** over Bluetooth Low Energy (BLE), extracts high-frequency (25Hz) binary IMU/GNSS telemetry, processes real-time attitude and hydrodynamics, hosts an interactive dark-mode telemetry dashboard, and streams live data into **Signal K** via an ultra-low-latency UDP data pipe.

---

## Technical Architecture Overview

The system architecture cleanly separates raw hardware telemetry ingestion, local monitoring, and core vessel server integration:


```

[RaceBox Micro]
│
▼ (25Hz Binary Stream via BLE)
[racebox_stream.py]
├──► (Local Logging) ──► Rolling Hourly CSV Logs
├──► (FastAPI WS) ────► 3D Canvas Horizon & Chart Dashboard (Port 8000)
│
▼ (JSON Deltas over Local UDP Port 20222)
[Signal K Server] ────► Instrument Displays / NMEA 2000 Gateway

```

---

## Installation & Setup

### 1. Install System Dependencies
Update your Raspberry Pi package index and install the required core system libraries:
```bash
sudo apt update
sudo apt install python3-pip python3-venv git -y

```

### 2. Project Deployment & Environment Setup

Clone the repository, initialize an isolated Python Virtual Environment (`venv`), and install the required asynchronous networking and hardware interface libraries:

```bash
cd ~/racebox_gps_imu_streaming
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install bleak fastapi uvicorn websocket-client

```

---

## Operational Workflows

### How to Run via Terminal

To spin up the hub manually for active debugging, console logs, or initial pairing verification:

```bash
cd ~/racebox_gps_imu_streaming
source venv/bin/activate
python3 racebox_stream.py

```

*The local web interface will become accessible immediately at `http://<your-pi-ip>:8000`.*

### How to Run as a System Service

To ensure the pipeline handles boot execution, automatic process crashes, and background recovery, run it through `systemd`.

1. **Create the Service File:**
```bash
sudo nano /etc/systemd/system/racebox.service

```


2. **Paste the Configuration:**
```ini
[Unit]
Description=Karukera RaceBox Telemetry Pipeline
After=network.target bluetooth.target

[Service]
Type=simple
User=theseal
WorkingDirectory=/home/theseal/racebox_gps_imu_streaming
ExecStart=/home/theseal/racebox_gps_imu_streaming/venv/bin/python3 /home/theseal/racebox_gps_imu_streaming/racebox_stream.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target

```


3. **Enable and Start the Service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable racebox.service
sudo systemctl start racebox.service

```


4. **Manage the Service:**
* **View live logs:** `sudo journalctl -u racebox.service -f`
* **Stop:** `sudo systemctl stop racebox.service`
* **Restart:** `sudo systemctl restart racebox.service`



### How to Update the Hub

When pulling new updates or code changes, use this sequence to prevent file locks:

```bash
cd ~/racebox_gps_imu_streaming
sudo systemctl stop racebox.service
git pull
sudo systemctl start racebox.service
sudo journalctl -u racebox.service -n 20 --no-pager

```

---

## Signal K Integration Setup

To link your 25Hz telemetry into your central navigation network, configure an isolated inward UDP port in the Signal K dashboard. This keeps transmission overhead light and robust.

1. Open your **Signal K Admin Dashboard** (`http://<pi-ip>:3000`).
2. Navigate to **Server** $\rightarrow$ **Data Connections**.
3. Click **Add** and configure the exact variables below:
* **Data Type:** `Signal K`
* **ID:** `racebox-udp`
* **Connection Type:** `UDP`
* **Port:** `20222`


4. Click **Submit** or **Apply**.
5. Click the orange **Restart** notification at the top of the Signal K window.
6. Verify live reception by going to the **Data Browser** tab; look for active keys matching `navigation.attitude` and `environment.wind.waveHeight`.

---

## 🗺️ Signal K Data Dictionary

The Hub pushes updates over local UDP port `20222` to `vessels.self`. To ensure parameters never disappear from your Signal K data browser or instrument displays when the boat is stationary, these paths are continuously streamed on every single valid sensor packet:

| Signal K Path | Type | Unit | Description / Trigger Behavior |
| :--- | :--- | :--- | :--- |
| `navigation.position` | Object | lat/lon | Live GNSS coordinates. |
| `navigation.speedOverGround` | Float | m/s | Vessel velocity converted from Knots to SI meters per second. |
| `navigation.courseOverGround` | Float | Radians | True heading calculated relative to the Earth's grid. |
| `navigation.gnss.hdop` | Float | Meter | Horizontal Dilution of Precision (Accuracy baseline). |
| `navigation.gnss.satellites` | Integer | Count | Active satellite vehicle count. |
| `navigation.attitude.roll` | Float | Radians | Port/Starboard heel angle (Relative to neutral tare baseline). |
| `navigation.attitude.pitch` | Float | Radians | Bow/Stern trim profile. |
| `environment.wind.waveHeight` | Float | Meter | Calculated wave amplitude from peak heave periods ($0.0$ at dock). |
| `environment.wind.wavePeriod` | Float | Second | Temporal duration of the active pitch/heave cycle wave match. |
| `performance.hull.slamAcceleration` | Float | $G$-Force | Continuous maximum lateral sway acceleration ($Y$-axis displacement). |

## Physics, Mathematics & Data Calculations

The telemetry engine relies on a mathematical process to extract clean vessel attitude information and calculate wave heights from raw accelerations and angular velocities.

### 1. Attitude Extraction (Pitch & Roll)

The IMU outputs raw linear acceleration across three orthagonal axes ($a_x$ = surge, $a_y$ = sway, $a_z$ = heave). When the boat changes orientation relative to gravity, the constant $1\text{G}$ gravity vector shifts across these axes.

* **Pitch ($\theta$):** Calculated by analyzing the ratio of forward acceleration against the lateral and vertical components:

$$\theta = \arctan2\left(-a_x, \sqrt{a_y^2 + a_z^2}\right)$$


* **Roll ($\phi$):** Calculated by analyzing the ratio of lateral acceleration against vertical acceleration:

$$\phi = \arctan2(a_y, a_z)$$



The script applies these calculations to correct mounting offsets on the fly when the "Neutral Tare" command is triggered via the UI.

### 2. Isolated Vertical Motion (True Heave)

To find out how high a wave lifts the boat, we must isolate the vertical acceleration vector relative to the *earth*, not the *vessel*. If the hull is rolled or pitched over while climbing a wave, raw $a_z$ is no longer looking straight up.

The script performs a coordinate transformation matrix rotation using the extracted Pitch ($\theta$) and Roll ($\phi$) angles to calculate **True Vertical Acceleration ($a_{\text{TrueZ}}$)**:


$$a_{\text{TrueZ}} = (a_x \cdot \sin\theta) - (a_y \cdot \sin\phi \cdot \cos\theta) + (a_z \cdot \cos\phi \cdot \cos\theta)$$

The baseline constant force of gravity ($1\text{G}$) is then subtracted to isolate purely dynamic vertical movement ($G_{\text{motion}} = a_{\text{TrueZ}} - 1.0$).

### 3. Hydrodynamic Wave-Height Ingestion

The script tracks vertical movement to catch individual wave cycles using a dynamic state machine:

1. **State Activation (Climbing):** When isolated acceleration spikes upward ($G_{\text{motion}} > 0.08\text{G}$), the script marks a wave encounter, starts a timer ($t_{\text{start}}$), and monitors the peak acceleration ($G_{\text{peak}}$).
2. **State Termination (Crest/Trough Transition):** When acceleration swings negative ($G_{\text{motion}} < -0.05\text{G}$), the wave duration ($t_{\text{duration}} = t_{\text{now}} - t_{\text{start}}$) is recorded.
3. **Double Integration Approximation:** For standard harmonic wave cycles, displacement (wave height) can be derived by integrating acceleration twice over time. The script applies a localized physics model using the measured peak acceleration and duration:

$$\text{Height (meters)} = 0.5 \cdot \left(G_{\text{peak}} \cdot 9.81\right) \cdot \left(\frac{t_{\text{duration}}}{2}\right)^2$$



### 4. Hull Slamming and Sea-State Classification

* **Slam Tracker:** The script continuously samples the lateral sway axis ($a_y$). Severe impacts or side-slams project extreme peak spikes into this variable, which are logged to the wave ledger to track hull fatigue.
* **Sea-State Classifier:** By maintaining a running 10-wave rolling average of calculated heights ($h_{\text{avg}}$) and periods ($t_{\text{avg}}$), the system classifies your operating context:
* $h_{\text{avg}} < 0.15\text{m} \rightarrow$ **Calm / Glass**
* $h_{\text{avg}} < 0.40\text{m} \rightarrow$ **Choppy / Short Chop** (or **Smooth Swell** if period is long)
* $h_{\text{avg}} \ge 0.70\text{m} \rightarrow$ **Rough / Confused Sea** (or **Heavy Ground Swell** if period is long)



```

```
