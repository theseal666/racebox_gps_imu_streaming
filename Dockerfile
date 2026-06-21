FROM python:3.11-slim

# Install system dependencies needed for Bluetooth / D-Bus communication
RUN apt-get update && apt-get install -y \
    bluez \
    dbus \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install standard dependencies
RUN pip install --no-cache-dir fastapi uvicorn bleak

COPY racebox_stream.py .

EXPOSE 8000

CMD ["python", "racebox_stream.py"]