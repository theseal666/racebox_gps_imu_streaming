# Karukera High-Speed Telemetry Hub

Karukera is a real-time marine telemetry system designed specifically for high-speed vessels. By combining raw high-frequency IMU data with sub-meter precision GNSS tracking from a RaceBox Micro, the system acts as an inertial navigation computer. It dynamically filters out hull vibrations, tracks precise boat attitude (Heel & Trim), profiles mechanical wave impacts (Slam Gs), and lists wave encounters in a rolling ledger—all delivered instantly to a web dashboard via low-latency WebSockets.

Project Repository: `https://github.com/theseal666/racebox_gps_imu_streaming/tree/main`

---

## Repository Installation & Updates

Because the universal setup script requires local file access to compile your host services, downloading the codebase and keeping it updated is handled directly via standard Git operations.

### Initial Repository Cloning

To pull a fresh copy of the application down to your local machine, open your terminal or command prompt and run:

```bash
git clone https://github.com/theseal666/racebox_gps_imu_streaming.git
cd racebox_gps_imu_streaming

```

### Pulling Future Updates

When changes are pushed to the main repository, you can update your local files by navigating to the project directory and pulling down the latest modifications:

```bash
git pull origin main

```

*Note: If you are running the hub as a background daemon or inside a running Docker container, make sure to restart your running service instance after executing a pull request to apply the code modifications.*

---

## Local Virtual Environment Setup

To keep dependencies isolated and avoid version conflicts with other Python projects on your machine, it is highly recommended to run the application inside a local Virtual Environment (`venv`).

Follow these steps based on your operating system to set up and activate the virtual environment folder before installing dependencies:

### macOS & Linux

1. Navigate to your cloned repository folder in the terminal and create the environment:
```bash
python3 -m venv venv

```


2. Activate the virtual environment:
```bash
source venv/bin/activate

```



### Windows

1. Open a command prompt, navigate to your repository folder, and create the environment:
```cmd
python -m venv venv

```


2. Activate the virtual environment:
```cmd
venv\Scripts\activate

```



*Note: Once activated, your terminal prompt will be prefixed with `(venv)`. Any package installed via pip will now live entirely isolated inside this local directory.*

---

## System Architecture & Dependencies

The backend engine is built on asynchronous Python architectures to process dense 25 Hz binary streams without blocking the UI rendering engine or disk I/O operations.

### Core Architecture Components

* **Bleak Async Pipeline:** Manages the low-level Bluetooth Low Energy (BLE) GATT connection notifications. It rebuilds incoming fragmented byte buffers back into structural hex chunks.
* **FastAPI & ASGI Event Loops:** Runs a local web server hosting an administrative API control panel alongside a high-frequency WebSocket state broadcaster.
* **Dynamic UI Canvas:** A featherweight browser frontend using Leaflet.js for high-precision vector track pathing and vanilla HTML5 canvas rendering engine for real-time 3D attitude visualization.

### Required Software Packages

With your virtual environment activated, run the following command to install the required Python libraries locally:

```bash
pip install fastapi uvicorn bleak

```

---

## Web Service Features & Interface Functions

The application serves a real-time, responsive telemetry dashboard accessible via any modern browser (default: `http://127.0.0.1:8000`). The web interface partitions functionality across distinct visual segments:

### Live Telemetry Header

Displays persistent, running data blocks aggregated across the WebSocket pipeline:

* **FREQ:** Real-time sensor stream rate (Hz). Drops dynamically when power-saving profiles are active.
* **HEEL & TRIM:** Instantaneous angular orientation readouts matching physical boat movement.
* **SPEED:** Accurate velocity parsed directly from raw knots data.
* **SATS & GPS ACCURACY:** Displays active GPS satellite count alongside live Horizontal Dilution of Precision (HDOP). The metric automatically changes color based on signal quality (Green for high accuracy, Amber for degradation, Red for low precision fixes).
* **BATTERY & POWER DRAW:** Live monitoring of voltage metrics and running power utilization calculated against device states.

### Administrative Controls

The upper right header provides immediate command endpoints interacting with the running Python system state:

* **Set Neutral Tare:** Triggers an API POST request to `/api/calibrate`. This snapshots current sensor data to use as a flat zero-baseline, correcting for any offset caused by how the hardware is mounted on a bulkhead.
* **Dock Mode (1Hz Log):** Triggers an API POST request to `/api/eco`. Toggles a power-saving mode that throttles calculations down to a 1 Hz interval to conserve system resources and storage when stationary.
* **Reset Bluetooth BLE:** Triggers an API POST request to `/api/reset`. Clears the cached hardware MAC configuration file (`racebox_config.txt`) and restarts the background scanning routine to pair with a new hardware device.

### Graphical Layout Elements

* **Interactive Vessel Mapping:** A dark-themed Leaflet map container tracking the vessel position history. It draws a persistent track line of all coordinates received while running. Includes a manual "Center On Boat" safety anchor to instantly snap the viewport frame back over your live map coordinates.
* **3D Horizon Space:** A hardware-accelerated artificial horizon box drawing an interactive model of the hull. It dynamically updates heel, trim, heave vertical lift, and yaw rotation rates directly on screen.
* **Rolling Wave Ledger:** A chronological impact ledger keeping trace of the last 10 classified wave encounters. It outputs unique wave IDs, mathematical height estimations, hull stress loads, and wave periods.
* **Time-Series Data Graphs:** Dual running Chart.js graph containers tracking raw historical motion variables. The top graph visualizes linear forces (Sway, Surge, True Vertical Heave), while the bottom tracks angular velocities (Roll, Pitch, Yaw Rates).

---

## Cross-Platform Installation & Service Deployment

This project includes a universal orchestration tool (`install.py`) that installs software dependencies and registers the backend telemetry script as an automated system service depending on your operating system.

### macOS Deployment (Native LaunchDaemon)

macOS uses a native `launchd` service architecture to run the application invisibly in the background on startup.

1. Run the multi-platform installer script:

```bash
python install.py

```

2. Manually register and start the daemon immediately:

```bash
launchctl load ~/Library/LaunchAgents/com.karukera.telemetry.plist

```

*Logs are outputted continuously to `/tmp/karukera.log` for debugging and performance auditing.*

### Windows Deployment (Silent Startup Background Script)

Windows handles persistent services by leveraging a combined batch script wrapped inside an invisible Visual Basic (`.vbs`) execution layer to suppress terminal windows from hanging open on your taskbar.

1. Run the setup compiler from an elevated command prompt:

```cmd
python install.py

```

2. The installer automatically hooks into the user `AppData\...\Programs\Startup` system profile folder.
3. The server launches invisibly whenever the Windows user profile loads.

### Linux Deployment (Isolated Docker Containerization)

Because Bluetooth kernel bindings can conflict heavily across different Linux distributions, a dedicated Docker virtualization environment is used. This isolates the app completely while giving it direct raw hardware access.

*(Note: If deploying via Docker, creating a local virtual environment on your host machine is unnecessary, as the container manages its own internal isolated Python layer automatically.)*

1. Ensure `docker` and `docker-compose` are installed on your Linux machine.
2. Spin up the cluster using host network bindings:

```bash
docker compose up -d --build

```

> **Note:** The `docker-compose.yml` mounts the system's host `/var/run/dbus` socket directly inside the container virtual space. This is required for `bleak` to communicate with your Linux host BlueZ Bluetooth adapter.

---

## How the Physics & Wave-Tracking Engines Work

The core of Karukera's intelligence lies in translating raw, noisy sensor data measured relative to the moving boat into fixed coordinates relative to the earth.

### 1. Sensor Orientation Calibration (Digital Taring)

If the physical RaceBox is mounted at a slight angle on a bulkhead, your baseline readings will be skewed. When you click **Set Neutral Tare**, the system snapshots the resting structural offsets (roll offset, pitch offset) and mathematically subtracts them from all subsequent raw inputs.

### 2. 3D Attitude Calculation (Heel & Trim)

The system tracks structural tilt by measuring how the constant gravity vector (1 G = 9.81 m/s²) distributes across the internal accelerometer axes.

* **Trim (Pitch):** Calculated by analyzing the forward-facing X-axis acceleration against the remaining combined lateral and vertical force vectors:
`Pitch = arctan2(-Ax, sqrt(Ay² + Az²)) - pitch_offset`
* **Heel (Roll):** Calculated by assessing the lateral tilt on the Y-axis against the vertical Z-axis vector:
`Roll = arctan2(Ay, Az) - roll_offset`

### 3. True Vertical Heave Extraction (Z-Axis Isolation)

When a boat crashes over waves, the internal Z-axis accelerometer experiences a complex mix of gravity, centrifugal force, and wave lift. To isolate the pure vertical movement of the water, the system rotates the boat's frame back into a global vertical plane using a geometric translation matrix:

`True Z = (Ax * sin(Pitch)) - (Ay * sin(Roll) * cos(Pitch)) + (Az * cos(Roll) * cos(Pitch))`

To find the actual acceleration from just the waves (Motion Z), we subtract Earth's constant gravity (1 G) and any calibration taring offset:

`Motion Z = True Z - 1.0 - z_offset`

### 4. Mathematical Wave Height Profiling (The Ledger Engine)

The rolling ledger does not just guess wave heights—it models individual wave periods using kinematic calculation loops:

```text
      Motion Z Acceleration
      
+0.08G - - - - - - - - /---\  State: "Climbing" (Trigger Wave Start)
                      /     \
  0.0G_______________/_______\_____________________ Time (s)
                    /         \
-0.05G - - - - - - - - - - - - \___  State: "Falling" (Trigger Evaluation)
                                   \___/

```

1. **Ascent Trigger:** When Motion Z spikes past a threshold (+0.08 G), a wave encounter is initiated. The system locks a high-precision `wave_start_time` stamp and tracks the maximum upward acceleration peak (`a_peak`).
2. **Descent Trigger:** When the acceleration drops through zero and falls past a negative threshold (-0.05 G), the boat has crested the wave. The system calculates the total transit duration (`t = now - wave_start_time`).
3. **Kinematic Displacement Equation:** If the transit duration matches a valid ocean wave period window (0.4s < t < 8.0s), the physical displacement (wave height in meters) is calculated by integrating the acceleration over time:
`Height (m) = 0.5 * (a_peak * 9.81) * (t / 2)²`
4. **Slam Analysis:** The maximum lateral force (`Ay`) recorded during this specific window is stamped as the wave's **Slam G**, providing an immediate metric of hull stress and wave steepness.
