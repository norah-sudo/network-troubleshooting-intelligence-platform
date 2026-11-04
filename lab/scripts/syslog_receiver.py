
import socket
from datetime import datetime, timezone
from pathlib import Path

HOST = "172.20.20.1"
PORT = 5514

LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "syslog.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
    server.bind((HOST, PORT))
    print(f"Syslog Receiver listening on {HOST}:{PORT}", flush=True)

    while True:
        data, address = server.recvfrom(8192)

        message = data.decode("utf-8", errors="replace").strip()

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        event = f"{timestamp} {address[0]} {message}"

        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(event + "\n")

        print(event, flush=True)
