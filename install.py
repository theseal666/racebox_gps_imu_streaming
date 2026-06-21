import os
import sys
import platform
import subprocess

def install_dependencies():
    print("📦 Installing required python packages...")
    packages = ["fastapi", "uvicorn", "bleak", "leaflet"]
    # Bleak requires specific OS backends, handled cleanly by pip
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)

def setup_mac_service(script_path):
    print("🍏 Configuring macOS launchd background daemon...")
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.karukera.telemetry</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/karukera.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/karukera_err.log</string>
</dict>
</plist>
"""
    target_dir = os.path.expanduser("~/Library/LaunchAgents")
    os.makedirs(target_dir, exist_ok=True)
    plist_path = os.path.join(target_dir, "com.karukera.telemetry.plist")
    
    with open(plist_path, "w") as f:
        f.write(plist_content)
        
    print(f"✅ Background service registered at: {plist_path}")
    print("👉 To start immediately, run: launchctl load " + plist_path)

def setup_windows_service(script_path):
    print("🪟 Configuring Windows background startup target...")
    startup_folder = os.path.join(os.environ["APPDATA"], "Microsoft\\Windows\\Start Menu\\Programs\\Startup")
    
    # We use a tiny VBS runner script so it launches seamlessly with NO visible cmd.exe window popping up on screen
    vbs_path = os.path.join(startup_folder, "launch_karukera.vbs")
    bat_path = os.path.join(os.path.dirname(script_path), "run_backend.bat")
    
    with open(bat_path, "w") as f:
        f.write(f'"{sys.executable}" "{script_path}"\n')
        
    with open(vbs_path, "w") as f:
        f.write(f'CreateObject("Wscript.Shell").Run "{bat_path}", 0, True\n')
        
    print(f"✅ Silent Startup script added to Windows User profile environment framework.")
    print("👉 It will now automatically deploy minimized whenever you boot or log into Windows.")

def main():
    current_os = platform.system()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_script = os.path.join(script_dir, "racebox_stream.py")
    
    if not os.path.exists(target_script):
        print(f"❌ Error: Could not locate racebox_stream.py in {script_dir}")
        return

    install_dependencies()

    if current_os == "Darwin":
        setup_mac_service(target_script)
    elif current_os == "Windows":
        setup_windows_service(target_script)
    elif current_os == "Linux":
        print("🐧 Linux detected. For Linux systems, deploying via Docker container virtualization is highly recommended.")
        print("👉 Use the provided Dockerfile configuration to spin up the container environment cleanly.")
    else:
        print("⚠️ Unknown platform structure configuration profiles.")

if __name__ == "__main__":
    main()