"""
FingerAttend — Local Python Controller & Attendance Logger (runs on PC over COM25)

Works directly with the current D5/D6 wiring via the ESP8266 board on COM25:
- Interactive commands:
    A / #<id>  : Enroll fingerprint at ID (1..127)
    R#<id>     : Remove fingerprint ID
    L          : List stored IDs & names
    Q          : Quit
- Automatically logs matched fingerprints to `attendance.csv` locally
  and (optionally) posts JSON to Google Apps Script `SCRIPT_URL`.
"""

import csv
import datetime
import json
import os
import sys
import threading
import urllib.request
import serial
import time

PORT = "COM25"
BAUD = 115200
CSV_FILE = os.path.join(os.path.dirname(__file__), "attendance.csv")
SCRIPT_URL = ""  # Optional: paste your Google Apps Script Web App URL here

NAME_MAP = {
    31: "Mani",
    2: "Gaurav",
    3: "Charlie",
    4: "Mani",
    5: "Eve",
    6: "Frank",
    7: "Grace",
    8: "Henry",
    9: "Isla",
    34: "DAVID",
    45: "Ram",
}


def get_name_by_id(fid: int) -> str:
    return NAME_MAP.get(fid, f"User_{fid}")


def log_attendance(fid: int):
    name = get_name_by_id(fid)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_file = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["Timestamp", "ID", "Name", "Status"])
        w.writerow([ts, fid, name, "Present"])
    print(f"[ATTENDANCE SAVED] {ts} | ID #{fid} | {name} | Present -> {CSV_FILE}")

    if SCRIPT_URL:
        try:
            payload = json.dumps({"id": fid, "name": name, "status": "Present"}).encode("utf-8")
            req = urllib.request.Request(SCRIPT_URL, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[GOOGLE SHEETS] HTTP {resp.status}: {resp.read().decode(errors='ignore')}")
        except Exception as e:
            print(f"[GOOGLE SHEETS] Failed: {e}")


def main():
    s = serial.Serial()
    s.port = PORT
    s.baudrate = BAUD
    s.timeout = 0.2
    s.dtr = False
    s.rts = False
    s.open()

    print(f"Connected to {PORT} @ {BAUD}. Commands: A | #<id> | R#<id> | L | Q")
    stop = False

    def reader():
        while not stop:
            try:
                line = s.readline()
                if line:
                    txt = line.decode("ascii", errors="ignore").rstrip()
                    if txt:
                        print(txt)
                        if txt.startswith("ATTENDANCE_LOG,"):
                            try:
                                parts = txt.split(",")
                                log_attendance(int(parts[1]))
                            except Exception:
                                pass
                        elif txt.startswith("Match: ID "):
                            try:
                                fid = int(txt.split("ID")[1].strip().split()[0])
                                log_attendance(fid)
                            except Exception:
                                pass
            except Exception:
                break

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        while True:
            cmd = input().strip()
            if cmd.upper() == "Q":
                break
            s.write((cmd + "\n").encode("ascii"))
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop = True
        s.close()


if __name__ == "__main__":
    main()
