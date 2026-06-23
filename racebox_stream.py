import asyncio
import struct
import os
import json
import time
import math
import socket
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn
from bleak import BleakScanner, BleakClient

CONFIG_FILE = "racebox_config.txt"
UART_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

UDP_IP = "127.0.0.1"
UDP_PORT = 20222

racebox_state = {
    "status": "Disconnected",
    "accel_x": 0.0, "accel_y": 0.0, "accel_z": 1.0,
    "gyro_x": 0.0, "gyro_y": 0.0, "gyro_z": 0.0,
    "latitude": 0.0, "longitude": 0.0, "speed_knots": 0.0,
    "satellites": 0, "hdop": 99.9, "voltage": 0.0, "power_w": 0.0,
    "hz": 0,
    "heel_deg": 0.0, "pitch_deg": 0.0, "true_z_g": 0.0,
    "current_wave_height": 0.0,
    "eco_mode": False,
    "sea_state": "Calm / Glass",
    "avg_wave_height": 0.0,
    "last_10_waves": [],
    "offset_roll": 0.0,
    "offset_pitch": 0.0,
    "offset_true_z": 0.0
}

connected_sockets = set()
binary_buffer = bytearray()
ble_trigger_reset = False

# Dedicated socket for UDP streaming
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

packet_count = 0
last_hz_time = time.time()
wave_history = []
wave_id_counter = 0

climbing = False
wave_start_time = time.time()
peak_z = 0.0
max_slam_y = 0.0
yaw_accumulator = 0.0

current_log_hour = ""
current_log_filename = ""
eco_throttle_counter = 0

def push_to_signal_k_udp(path: str, value: float):
    """Pushes a single telemetry update to Signal K over local UDP"""
    delta_payload = {
        "context": "vessels.self",
        "updates": [
            {
                "source": {"label": "karukera-telemetry-hub"},
                "values": [{"path": path, "value": value}]
            }
        ]
    }
    try:
        message = json.dumps(delta_payload).encode('utf-8')
        udp_sock.sendto(message, (UDP_IP, UDP_PORT))
    except Exception:
        pass

def write_to_csv_log(timestamp_str, ax, ay, az, gx, gy, gz, heel, pitch, knots, lat, lon, wave_height):
    global current_log_hour, current_log_filename
    now_hour = datetime.now().strftime("%Y-%m-%d-%H")
    
    if now_hour != current_log_hour:
        current_log_hour = now_hour
        current_log_filename = f"racebox_log_{current_log_hour}.csv"
        if not os.path.exists(current_log_filename):
            with open(current_log_filename, "w") as f:
                f.write("timestamp,accel_x,accel_y,accel_z,gyro_x,gyro_y,gyro_z,heel_deg,pitch_deg,speed_knots,latitude,longitude,calculated_wave_height_m\n")
                
    try:
        log_line = f"{timestamp_str},{ax:.3f},{ay:.3f},{az:.3f},{gx:.1f},{gy:.1f},{gz:.1f},{heel:.1f},{pitch:.1f},{knots:.1f},{lat:.8f},{lon:.8f},{wave_height:.2f}\n"
        with open(current_log_filename, "a") as f:
            f.write(log_line)
    except Exception as e:
        print(f"CSV Logging error: {e}")

def update_sea_state_metrics():
    if not wave_history:
        racebox_state["sea_state"] = "Calm / Glass"
        racebox_state["avg_wave_height"] = 0.0
        return
        
    total_h = sum(w["height"] for w in wave_history)
    total_p = sum(w["period"] for w in wave_history)
    avg_h = total_h / len(wave_history)
    avg_p = total_p / len(wave_history)
    
    racebox_state["avg_wave_height"] = round(avg_h, 2)
    
    if avg_h < 0.15:
        racebox_state["sea_state"] = "Calm / Glass"
    elif avg_h < 0.40:
        racebox_state["sea_state"] = "Choppy / Short Chop" if avg_p < 2.2 else "Smooth SWELL"
    elif avg_h >= 0.70:
        racebox_state["sea_state"] = "Rough / Confused Sea" if avg_p < 3.5 else "Heavy Ground Swell"
    else:
        racebox_state["sea_state"] = "Moderate Swell"

def analyze_motion_and_waves(ax, ay, az, gx, gy, gz, lat, lon, knots):
    global climbing, wave_start_time, peak_z, max_slam_y, wave_id_counter, yaw_accumulator
    
    denom = math.sqrt(ay**2 + az**2) + 0.0001
    pitch = math.atan2(-ax, denom)
    roll = math.atan2(ay, az)
    
    roll_deg = math.degrees(roll) - racebox_state["offset_roll"]
    pitch_deg = math.degrees(pitch) - racebox_state["offset_pitch"]
    
    racebox_state["pitch_deg"] = round(pitch_deg, 1)
    racebox_state["heel_deg"] = round(roll_deg, 1)
    yaw_accumulator = (yaw_accumulator + (gz * 0.04)) % 360
    
    # Forward attitude paths instantly to Signal K UDP server (converted to radians)
    push_to_signal_k_udp("navigation.attitude.roll", float(math.radians(roll_deg)))
    push_to_signal_k_udp("navigation.attitude.pitch", float(math.radians(pitch_deg)))
    
    true_z = (ax * math.sin(pitch)) - (ay * math.sin(roll) * math.cos(pitch)) + (az * math.cos(roll) * math.cos(pitch))
    motion_z_g = true_z - 1.0 - racebox_state["offset_true_z"]
    racebox_state["true_z_g"] = round(motion_z_g, 3)
    
    if abs(ay) > max_slam_y:
        max_slam_y = abs(ay)

    now = time.time()
    calculated_height = racebox_state["current_wave_height"]

    if not climbing and motion_z_g > 0.08:
        climbing = True
        peak_z = motion_z_g
        wave_start_time = now
    elif climbing and motion_z_g > peak_z:
        peak_z = motion_z_g
    elif climbing and motion_z_g < -0.05:
        climbing = False
        wave_duration = now - wave_start_time
        
        if 0.4 < wave_duration < 8.0:
            avg_accel = (peak_z * 9.81) 
            calculated_height = 0.5 * avg_accel * ((wave_duration / 2) ** 2)
            calculated_height = round(max(0.1, min(calculated_height, 6.5)), 2)
            racebox_state["current_wave_height"] = calculated_height
            
            # Forward dynamic calculation to Signal K over UDP using standardized spec paths
            push_to_signal_k_udp("environment.wind.waveHeight", float(calculated_height))
            
            clearance_ratio = calculated_height / wave_duration
            if clearance_ratio > 0.6:   steepness = "STEEP / WALL"
            elif clearance_ratio > 0.3: steepness = "MODERATE"
            else:                       steepness = "LONG SWELL"
            
            wave_id_counter += 1
            wave_history.insert(0, {
                "id": wave_id_counter,
                "height": calculated_height,
                "steepness": steepness,
                "slam_g": round(max_slam_y, 2),
                "period": round(wave_duration, 1)
            })
            if len(wave_history) > 10: wave_history.pop()
            racebox_state["last_10_waves"] = wave_history
            update_sea_state_metrics()
            
        max_slam_y = 0.0

    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    write_to_csv_log(timestamp_str, ax, ay, az, gx, gy, gz, roll_deg, pitch_deg, knots, lat, lon, calculated_height)

def handle_racebox_binary(sender, data: bytearray):
    global binary_buffer, packet_count, last_hz_time, eco_throttle_counter
    
    binary_buffer.extend(data)
    while True:
        header_index = binary_buffer.find(b'\xB5\x62')
        if header_index == -1:
            if len(binary_buffer) > 1: binary_buffer = binary_buffer[-1:]
            break
        if header_index > 0: del binary_buffer[:header_index]
        if len(binary_buffer) < 6: break
            
        payload_len = struct.unpack('<H', binary_buffer[4:6])[0]
        total_packet_len = 6 + payload_len + 2 
        if len(binary_buffer) < total_packet_len: break
            
        packet = binary_buffer[:total_packet_len]
        del binary_buffer[:total_packet_len]
        
        if packet[2] == 0xFF and packet[3] == 0x01:
            if racebox_state["eco_mode"]:
                eco_throttle_counter += 1
                if eco_throttle_counter % 25 != 0:
                    continue

            payload = packet[6:6+payload_len]
            try:
                packet_count += 1
                now = time.time()
                if now - last_hz_time >= 1.0:
                    racebox_state["hz"] = int(packet_count / (now - last_hz_time)) if not racebox_state["eco_mode"] else 1
                    packet_count = 0
                    last_hz_time = now

                racebox_state["satellites"] = int(payload[23])
                
                lon = struct.unpack('<i', payload[24:28])[0] / 10000000.0
                lat = struct.unpack('<i', payload[28:32])[0] / 10000000.0
                racebox_state["longitude"] = lon
                racebox_state["latitude"] = lat
                
                knots = round((struct.unpack('<i', payload[48:52])[0] / 1000.0) * 1.94384, 1)
                racebox_state["speed_knots"] = knots
                racebox_state["hdop"] = round(struct.unpack('<I', payload[40:44])[0] / 1000.0, 1)

                volt_raw = payload[67]
                racebox_state["voltage"] = round(volt_raw / 10.0, 2) if volt_raw > 0 else 4.10
                racebox_state["power_w"] = round((racebox_state["voltage"] * (0.02 if racebox_state["eco_mode"] else 0.12)), 2)

                ax = struct.unpack('<h', payload[68:70])[0] / 1000.0
                ay = struct.unpack('<h', payload[70:72])[0] / 1000.0
                az = struct.unpack('<h', payload[72:74])[0] / 1000.0
                racebox_state["accel_x"], racebox_state["accel_y"], racebox_state["accel_z"] = round(ax,2), round(ay,2), round(az,2)
                
                gx, gy, gz = struct.unpack('<h', payload[74:76])[0]/10.0, struct.unpack('<h', payload[76:78])[0]/10.0, struct.unpack('<h', payload[78:80])[0]/10.0
                racebox_state["gyro_x"], racebox_state["gyro_y"], racebox_state["gyro_z"] = round(gx,1), round(gy,1), round(gz,1)

                analyze_motion_and_waves(ax, ay, az, gx, gy, gz, lat, lon, knots)
                asyncio.run_coroutine_threadsafe(broadcast_state(), asyncio.get_event_loop())
            except Exception:
                pass

async def broadcast_state():
    if connected_sockets:
        message = json.dumps(racebox_state)
        await asyncio.gather(*[ws.send_text(message) for ws in connected_sockets], return_exceptions=True)

async def update_status(new_status: str):
    racebox_state["status"] = new_status
    await broadcast_state()

async def bluetooth_pipeline():
    global ble_trigger_reset
    while True:
        if ble_trigger_reset:
            if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
            ble_trigger_reset = False
        
        saved_uuid = None
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f: saved_uuid = f.read().strip()
        
        await update_status("Scanning...")
        devices = await BleakScanner.discover(timeout=3.0)
        target_device = next((d for d in devices if d.address == saved_uuid or (d.name and d.name.startswith("RaceBox Micro"))), None)
        
        if not target_device:
            await update_status("Device Not Found")
            await asyncio.sleep(4)
            continue
            
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "w") as f: f.write(target_device.address)

        await update_status("Connecting...")
        try:
            async with BleakClient(target_device) as client:
                if client.is_connected:
                    await update_status("Connected")
                    await client.start_notify(UART_TX_CHAR_UUID, handle_racebox_binary)
                    
                    activation_command = bytes([0xB5, 0x62, 0xFF, 0x01, 0x02, 0x00, 0x01, 0x00, 0x03, 0x04])
                    await client.write_gatt_char(UART_RX_CHAR_UUID, activation_command, response=False)
                    
                    while client.is_connected and not ble_trigger_reset:
                        await asyncio.sleep(0.5)
                    if ble_trigger_reset: await client.disconnect()
        except Exception as e:
            print(f"Session drop: {e}")
        await update_status("Disconnected")
        await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app: FastAPI):
    bg_task = asyncio.create_task(bluetooth_pipeline())
    yield
    bg_task.cancel()
    # Safely tear down UDP resource on exit
    udp_sock.close()

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def get_dashboard(): return HTMLResponse(html_content)

@app.post("/api/reset")
async def reset_hardware_profile():
    global ble_trigger_reset
    ble_trigger_reset = True
    return {"status": "Resetting cache profile loop..."}

@app.post("/api/eco/{state}")
async def toggle_eco(state: str):
    racebox_state["eco_mode"] = (state == "true")
    return {"status": f"Eco mode changed to {racebox_state['eco_mode']}"}

@app.post("/api/calibrate")
async def calibrate_sensor_baselines():
    racebox_state["offset_roll"] += racebox_state["heel_deg"]
    racebox_state["offset_pitch"] += racebox_state["pitch_deg"]
    racebox_state["offset_true_z"] += racebox_state["true_z_g"]
    return {"status": "IMU Tared Successfully"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_sockets.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: connected_sockets.remove(websocket)

html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Karukera Telemetry Hub</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: -apple-system, sans-serif; background: #0f141c; color: #e2e8f0; margin: 0; padding: 8px; height: 100vh; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden; }
        .header-bar { display: flex; justify-content: space-between; align-items: center; background: #1e293b; padding: 5px 12px; border-radius: 6px; margin-bottom: 6px; border: 1px solid #334155; flex-shrink: 0; }
        .header-title { font-size: 14px; font-weight: 800; color: #fff; margin: 0; }
        .metrics-row { display: flex; gap: 15px; align-items: center; font-size: 12px; font-weight: 600; color: #94a3b8; }
        .metric-val { color: #38bdf8; font-weight: 800; }
        .right-controls { display: flex; gap: 12px; align-items: center; }
        .status-badge { padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: bold; background: #475569; color: #fff; text-transform: uppercase; }
        .status-connected { background: #16a34a; }
        .status-scanning { background: #d97706; }
        .status-disconnected { background: #dc2626; }
        
        .mode-btn { font-size: 11px; font-weight: bold; background: #334155; color: #fff; border: 1px solid #475569; padding: 3px 8px; border-radius: 4px; cursor: pointer; }
        .mode-btn:hover { background: #475569; }
        .eco-active { background: #15803d !important; border-color: #22c55e; }

        .main-dashboard { display: grid; grid-template-columns: 1fr 310px 340px; gap: 6px; height: 48vh; min-height: 0; margin-bottom: 6px; flex-shrink: 0; }
        #map { height: 100%; width: 100%; border-radius: 6px; border: 1px solid #334155; position: relative; overflow: hidden; }
        .map-control-btn { position: absolute; bottom: 10px; right: 10px; z-index: 1000; background: #1e293b; color: #38bdf8; border: 1px solid #334155; padding: 5px 10px; font-size: 11px; font-weight: bold; border-radius: 4px; cursor: pointer; }
        .map-control-btn:hover { background: #334155; }
        
        .orientation-box { background: #1e293b; border-radius: 6px; border: 1px solid #334155; padding: 8px; display: flex; flex-direction: column; justify-content: space-between; align-items: center; overflow: hidden; }
        .panel-title { font-size: 11px; font-weight: 800; text-transform: uppercase; color: #94a3b8; width: 100%; border-bottom: 1px solid #334155; padding-bottom: 4px; text-align: left; }
        
        .sea-state-banner { width: 100%; background: #151f32; padding: 6px; border-radius: 4px; margin-bottom: 6px; display: flex; justify-content: space-between; box-sizing: border-box; border-left: 3px solid #38bdf8; font-size: 11px; }
        
        #attitudeCanvas { background: #151f32; border-radius: 4px; width: 100%; height: 85%; }

        .ledger-container { background: #1e293b; border-radius: 6px; border: 1px solid #334155; padding: 8px; display: flex; flex-direction: column; overflow: hidden; }
        .wave-table { width: 100%; border-collapse: collapse; font-size: 11px; text-align: left; }
        .wave-table th { color: #64748b; font-weight: 700; padding: 3px; border-bottom: 1px solid #334155; }
        .wave-table td { padding: 4px 3px; border-bottom: 1px solid #1e293b; font-weight: 600; }
        
        .charts-wrapper { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; flex: 1; min-height: 0; }
        .chart-container { background: #1e293b; padding: 6px; border-radius: 6px; border: 1px solid #334155; display: flex; flex-direction: column; min-height: 0; position: relative; overflow: hidden; }
        canvas { width: 100% !important; height: 100% !important; }
    </style>
</head>
<body>
    <div class="header-bar">
        <h2 class="header-title">🛥️ KARUKERA <span style="color:#38bdf8; font-weight:400; font-size:11px;">High Speed GPS & IMU-Tool</span></h2>
        <div class="metrics-row">
            <div>FREQ: <span id="hz" class="metric-val">0</span>Hz</div>
            <div>HEEL: <span id="heel" class="metric-val" style="color:#f59e0b;">0.0°</span></div>
            <div>TRIM: <span id="pitch" class="metric-val" style="color:#a855f7;">0.0°</span></div>
            <div>SPEED: <span id="speed" class="metric-val" style="color:#06b6d4;">0.0</span>kn</div>
            <div>SATS: <span id="sats" class="metric-val" style="color:#22c55e;">0</span></div>
            <div>GPS ACCURACY: <span id="hdop" class="metric-val" style="color:#e11d48;">99.9</span>m</div>
            <div>BATTERY: <span id="voltage" class="metric-val">0.00</span>V</div>
            <div>POWER DRAW: <span id="power" class="metric-val" style="color:#ec4899;">0.00</span>W</div>
        </div>
        <div class="right-controls">
            <button class="mode-btn" style="border-color:#10b981;" onclick="triggerSensorTare()">Set Neutral Tare</button>
            <button id="ecoBtn" class="mode-btn" onclick="toggleEcoMode()">Dock Mode (1Hz Log)</button>
            <button class="mode-btn" style="border-color:#ef4444;" onclick="triggerProfileReset()">Reset Bluetooth BLE</button>
            <div id="statusIndicator" class="status-badge">Checking...</div>
        </div>
    </div>

    <div class="main-dashboard">
        <div id="map">
            <button class="map-control-btn" onclick="centerMapOnVessel()">Center On Boat</button>
        </div>
        
        <div class="orientation-box">
            <div class="panel-title">📐 MAT 12.20 3D Horizon Space</div>
            <canvas id="attitudeCanvas"></canvas>
        </div>

        <div class="ledger-container">
            <div class="panel-title" style="border-bottom:none; padding-bottom:0;">🌊 Rolling Ledger: Last 10 Waves</div>
            <div class="sea-state-banner">
                <div>SEA STATE: <span id="seaStateTxt" style="color:#38bdf8; font-weight:bold;">Calm / Glass</span></div>
                <div>AVG HGT: <span id="avgHeightTxt" style="color:#10b981; font-weight:bold;">0.00m</span></div>
            </div>
            <div style="overflow-y: auto; flex: 1;">
                <table class="wave-table">
                    <thead>
                        <tr>
                            <th>WAVE ID</th>
                            <th>HEIGHT</th>
                            <th>STEEPNESS</th>
                            <th>SLAM</th>
                            <th>PERIOD</th>
                        </tr>
                    </thead>
                    <tbody id="waveLedgerBody">
                        <tr><td colspan="5" style="color:#64748b; text-align:center; padding-top:20px;">Awaiting wave impacts...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="charts-wrapper">
        <div class="chart-container"><canvas id="accelChart"></canvas></div>
        <div class="chart-container"><canvas id="gyroChart"></canvas></div>
    </div>

    <script>
        const map = L.map('map').setView([0, 0], 2);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png').addTo(map);
        
        const marker = L.marker([0, 0]).addTo(map);
        
        let positionHistory = [];
        const maxTrackPoints = 86400; 
        const trackLine = L.polyline([], {color: '#38bdf8', weight: 3, opacity: 0.85}).addTo(map);
        
        let initialFixAcquired = false;
        let currentLat = 0;
        let currentLon = 0;

        function centerMapOnVessel() {
            if (currentLat !== 0 && currentLon !== 0) {
                map.setView([currentLat, currentLon], 15);
                map.invalidateSize();
            }
        }

        const attCanvas = document.getElementById('attitudeCanvas');
        const attCtx = attCanvas.getContext('2d');
        let relativeHeading = 0;
        let ecoModeActive = false;
        
        function resizeAttitudeCanvas() {
            attCanvas.width = attCanvas.clientWidth; attCanvas.height = attCanvas.clientHeight;
        }
        window.addEventListener('resize', resizeAttitudeCanvas);
        setTimeout(resizeAttitudeCanvas, 200);

        function draw3DAttitude(heel, pitch, heave, gyroZ) {
            const w = attCanvas.width; const h = attCanvas.height;
            attCtx.clearRect(0, 0, w, h);
            relativeHeading = (relativeHeading + (gyroZ * 0.03)) % 360;
            attCtx.strokeStyle = '#1e293b'; attCtx.lineWidth = 1;
            for(let i=1; i<6; i++) {
                attCtx.beginPath(); attCtx.moveTo(0, h * (i/6)); attCtx.lineTo(w, h * (i/6)); attCtx.stroke();
            }
            attCtx.save();
            attCtx.translate(w/2, h * 0.65); attCtx.rotate(-relativeHeading * Math.PI / 180);
            attCtx.strokeStyle = 'rgba(56, 189, 248, 0.2)'; attCtx.lineWidth = 1.5;
            attCtx.beginPath(); attCtx.ellipse(0, 0, 80, 25, 0, 0, 2 * Math.PI); attCtx.stroke();
            attCtx.restore();

            attCtx.save();
            attCtx.translate(w / 2, (h / 2) + (heave * -35));
            attCtx.rotate(heel * Math.PI / 180);
            attCtx.fillStyle = '#1d4ed8'; attCtx.strokeStyle = '#38bdf8'; attCtx.lineWidth = 2;
            attCtx.beginPath();
            attCtx.moveTo(-50, 0); attCtx.lineTo(0, -12 + (Math.sin(pitch * Math.PI / 180) * 45)); attCtx.lineTo(50, 0); attCtx.lineTo(35, 18); attCtx.lineTo(0, 24); attCtx.lineTo(-35, 18);
            attCtx.closePath(); attCtx.fill(); attCtx.stroke();
            attCtx.restore();
        }

        const chartOptions = { 
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { labels: { color: '#94a3b8', boxWidth: 10 } } },
            scales: { x: { display: false }, y: { grid: { color: '#334155' }, ticks: { color: '#64748b' } } }
        };

        const accelChart = new Chart(document.getElementById('accelChart').getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'X (Sway)', data: [], borderColor: '#ef4444', borderWidth: 1, pointRadius: 0 },
                { label: 'Y (Surge)', data: [], borderColor: '#22c55e', borderWidth: 1, pointRadius: 0 },
                { label: 'True Z', data: [], borderColor: '#38bdf8', borderWidth: 1.5, pointRadius: 0 }
            ]},
            options: chartOptions
        });

        const gyroChart = new Chart(document.getElementById('gyroChart').getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [
                { label: 'Roll Rate', data: [], borderColor: '#a855f7', borderWidth: 1, pointRadius: 0 },
                { label: 'Pitch Rate', data: [], borderColor: '#f59e0b', borderWidth: 1, pointRadius: 0 },
                { label: 'Yaw Rate', data: [], borderColor: '#06b6d4', borderWidth: 1, pointRadius: 0 }
            ]},
            options: chartOptions
        });

        function toggleEcoMode() {
            ecoModeActive = !ecoModeActive;
            fetch(`/api/eco/${ecoModeActive}`, { method: 'POST' });
            document.getElementById('ecoBtn').className = "mode-btn" + (ecoModeActive ? " eco-active" : "");
        }

        function triggerSensorTare() {
            if(confirm("Ensure boat is stationary in calm water before setting neutral calibration context. Proceed?")) {
                fetch("/api/calibrate", { method: 'POST' });
            }
        }

        function triggerProfileReset() {
            if(confirm("Confirm resetting hardware pairing cache profile?")) {
                fetch("/api/reset", { method: 'POST' });
            }
        }

        const ws = new WebSocket(`ws://${window.location.host}/ws`);
        ws.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            document.getElementById('statusIndicator').innerText = data.status.toUpperCase();
            document.getElementById('hz').innerText = data.hz;
            document.getElementById('heel').innerText = data.heel_deg.toFixed(1) + "°";
            document.getElementById('pitch').innerText = data.pitch_deg.toFixed(1) + "°";
            document.getElementById('speed').innerText = data.speed_knots.toFixed(1);
            document.getElementById('sats').innerText = data.satellites;
            
            if (document.getElementById('hdop')) {
                document.getElementById('hdop').innerText = data.hdop.toFixed(1);
                document.getElementById('hdop').style.color = data.hdop <= 1.5 ? '#22c55e' : (data.hdop <= 3.0 ? '#f59e0b' : '#ef4444');
            }
            
            document.getElementById('voltage').innerText = data.voltage.toFixed(2);
            if(document.getElementById('power')) {
                document.getElementById('power').innerText = data.power_w.toFixed(2);
            }
            
            document.getElementById('seaStateTxt').innerText = data.sea_state;
            document.getElementById('avgHeightTxt').innerText = data.avg_wave_height.toFixed(2) + "m";

            draw3DAttitude(data.heel_deg, data.pitch_deg, data.true_z_g, data.gyro_z);

            if(data.latitude !== 0 && data.longitude !== 0) {
                currentLat = data.latitude;
                currentLon = data.longitude;
                marker.setLatLng([currentLat, currentLon]);

                if (positionHistory.length === 0 || 
                    positionHistory[positionHistory.length - 1][0] !== currentLat || 
                    positionHistory[positionHistory.length - 1][1] !== currentLon) {
                    
                    positionHistory.push([currentLat, currentLon]);
                    if (positionHistory.length > maxTrackPoints) {
                        positionHistory.shift();
                    }
                    trackLine.setLatLngs(positionHistory);
                }

                if (!initialFixAcquired) {
                    centerMapOnVessel();
                    initialFixAcquired = true;
                }
            }

            if (data.status === "Connected" && !data.eco_mode) {
                const timestamp = new Date().toLocaleTimeString();
                
                accelChart.data.labels.push(timestamp);
                accelChart.data.datasets[0].data.push(data.accel_x);
                accelChart.data.datasets[1].data.push(data.accel_y);
                accelChart.data.datasets[2].data.push(data.true_z_g);
                
                gyroChart.data.labels.push(timestamp);
                gyroChart.data.datasets[0].data.push(data.gyro_x);
                gyroChart.data.datasets[1].data.push(data.gyro_y);
                gyroChart.data.datasets[2].data.push(data.gyro_z);

                if(accelChart.data.labels.length > 60) {
                    accelChart.data.labels.shift(); accelChart.data.datasets.forEach(d => d.data.shift());
                    gyroChart.data.labels.shift(); gyroChart.data.datasets.forEach(d => d.data.shift());
                }
                accelChart.update('none'); gyroChart.update('none');
            }

            if(data.last_10_waves && data.last_10_waves.length > 0) {
                let html = "";
                data.last_10_waves.forEach(w => {
                    html += `<tr>
                                <td style="color:#64748b;">#${w.id}</td>
                                <td style="color:#38bdf8;">${w.height.toFixed(2)}m</td>
                                <td>${w.steepness}</td>
                                <td>${w.slam_g.toFixed(2)}G</td>
                                <td>${w.period.toFixed(1)}s</td>
                             </tr>`;
                });
                document.getElementById('waveLedgerBody').innerHTML = html;
            }
        };
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
