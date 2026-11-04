
import socket
import subprocess
import threading
import time
from datetime import datetime

RECEIVER = ("172.20.20.1", 5514)


def forward_logs(router):
    container = f"clab-ospftest-{router}"

    command = [
        "docker", "logs",
        "--follow",
        "--tail", "0",
        "--timestamps",
        container,
    ]

    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for line in process.stdout:
                message = line.strip()
                if not message:
                    continue

                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                event = f"<134>1 {timestamp} {router} frr-docker - - - {message}"

                sock.sendto(event.encode("utf-8"), RECEIVER)
                print(f"[{router}] {message}", flush=True)


for router in ("r1", "r2"):
    threading.Thread(
        target=forward_logs,
        args=(router,),
        daemon=True,
    ).start()

print("Forwarding new FRRouting logs from R1 and R2...")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Log forwarding stopped.")
