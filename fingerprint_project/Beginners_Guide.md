# FingerAttend: from a blinking LED to an attendance record

This guide follows the build in this folder. The folder is called `esp32`, but the chip we identified over USB is an **ESP8266EX**. Select **NodeMCU 1.0 (ESP-12E Module)** / PlatformIO `nodemcuv2`, not an ESP32 board.

## What runs where?

| Part | Its job |
| --- | --- |
| Optical fingerprint module | Captures a finger, extracts identifying features, and stores a **template** (a representation used for comparison) under a numerical ID. Matching happens here. |
| ESP8266 running Arduino C++ | Asks the sensor to enroll or match, prompts on the SSD1306 OLED, and plays tones on a passive buzzer. Its source is `sensor_test\src\main.cpp`, despite the folder name. |
| Windows PC running Python | `local_attendance.py` accepts commands and listens over USB. On a match event it maps the ID to a name and writes the PC time, ID, name and status to `attendance.csv`. It does not need a fingerprint image. |

`bringup.py` was our MicroPython hardware check. `main.py` and `r307.py` are the separate MicroPython port, **not** the program currently running on the board. Don't upload them or flash MicroPython to run the local attendance demo. Google Sheets is optional; no Wi-Fi credentials are needed for the USB logger.

## 1. Connect the parts

Use a USB **data** cable, NodeMCU, jumper wires, serial fingerprint module, 128 x 64 I2C SSD1306 OLED, and a passive buzzer rated for the chosen drive circuit. Disconnect USB before moving wires. D-labels are the labels printed on the NodeMCU, not GPIO numbers.

| Peripheral signal | NodeMCU connection | Why |
| --- | --- | --- |
| OLED SDA / SCL | D2 (GPIO4) / D1 (GPIO5) | I2C data / clock; this screen answered at address `0x3C`. |
| OLED power | 3V3 and GND | Use a 3.3 V-compatible module. |
| Sensor TX / RX | D5 (GPIO14) / D6 (GPIO12) | Cross the signals: the sensor's transmitter goes to the board's receiver. Sensor link: 57600 baud. |
| Sensor VCC / GND | Rated supply / common GND | Check the exact sensor's pinout and voltage, not wire colors. The reference uses VIN for a 5 V-rated module; never assume every sensor takes 5 V. ESP8266 data pins require 3.3 V logic. |
| Passive buzzer signal / return | D3 (GPIO0) / GND | PWM (rapid pulses) sets the pitch. GPIO0 is also a boot pin; don't pull it low at reset. |

## 2. How we brought it up

1. **Prove the USB link.** Windows initially saw a CP2102 device but no usable port. After the Silicon Labs CP210x driver was installed, Device Manager showed **COM25**. The chip identification and LED blink test established that the ESP8266 was running our code.
2. **Test the outputs separately.** A MicroPython I2C scan found `0x3C`. We showed text at full contrast and listened for three tones at 2000, 2700 and 3500 Hz. An address alone did not prove the display was visible; someone checked the screen and sound.
3. **Test the sensor before enrolling anyone.** Arduino `SoftwareSerial` let us keep the verified D5/D6 wiring and the USB console simultaneously. With a startup wait and retries, the sensor answered 30/30 handshake attempts; three finger placements produced three successful feature extractions. Detection is not enrollment: an empty database cannot produce a match.
4. **Integrate and handle bad scans.** We built the firmware with PlatformIO's Arduino framework and the Adafruit fingerprint, SSD1306 and GFX libraries. After a second enrollment image failed to convert, the firmware was changed to confirm contact, wait 150 ms, then capture again. It can retry a scan up to five times rather than immediately discarding the first good scan.

## 3. Run the local demo (already-flashed board)

In VS Code choose **Terminal > New Terminal**, not **Output**. Run:

```powershell
cd "$env:USERPROFILE\Downloads\esp32\fingerprint_project"
python local_attendance.py
```

If Python reports `No module named 'serial'`, run `python -m pip install pyserial` and try again. If Windows assigns a different port, update `PORT` in `local_attendance.py`. Wait for `Connected to COM25 @ 115200`. The USB link runs at 115200; the separate sensor link runs at 57600.

| In the running controller | What to do or expect |
| --- | --- |
| `L` | List stored IDs. Choose an unused ID from 1 to 127 to avoid overwriting an enrollment. |
| `#27` | Example **only if ID 27 is free**. Place a clean finger pad flat and still, lift completely when asked, then place the same finger again. Wait for `ENROLLED!` before testing. |
| Present that finger again | Keep the controller running. Lift after recognition; look for `[ATTENDANCE SAVED]` in the terminal and a new row in `attendance.csv`. The OLED alone does not confirm a disk write. |
| `Q` | Quit and release the COM port. |
| `R#27` | Deletes template 27. Use only to intentionally remove that enrollment. It does not delete earlier attendance rows. |

The PC uses `NAME_MAP` in `local_attendance.py`, not the name typed after the ID, for the CSV. Set that mapping before logging a new person and restart the controller. Custom names supplied to the board are held in RAM, unlike the sensor templates. For a demo, use a consenting volunteer and avoid projecting real attendance records.

## 4. If a step fails

| Symptom | First check |
| --- | --- |
| Cannot type / read-only editor | Start the controller in **Terminal**. Stop the old Code Runner session first; two programs cannot share COM25. |
| Port missing / access denied | Check Device Manager and the USB data cable. Close other serial monitors. |
| Blue sensor light, but no response | Light indicates power, not communication. Verify common ground, crossed TX/RX, rated supply and startup wait. |
| `Convert Failed` | Wipe the glass with a clean dry cloth. Lift fully, then place the same pad flat without sliding. If failures persist, record the scan number and hex code printed in Terminal. |
| Match displayed, no CSV row | Confirm the PC logger was connected when the scan happened and the CSV is writable. Missed USB events are not automatically replayed. |

**Source and next steps:** `reference_esp8266.ino` is the local snapshot of the reference attendance firmware; `google_script.gs` is the optional Sheets receiver. Before wider use, add duplicate protection, a persistent roster, administrator-only enrollment, an offline queue, and a retention/deletion policy. Offer a non-biometric attendance option.
