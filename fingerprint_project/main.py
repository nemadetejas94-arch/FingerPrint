# FingerAttend — MicroPython port of projectswithmani/FingerPrint-attendance
# Includes the bring-up fixes verified on hardware:
#   1. 1-second startup delay + 30-attempt handshake retry for sensor boot
#   2. Higher resonant buzzer frequencies (2000-3500 Hz) so passive buzzer is audible
#   3. Full OLED contrast (255) on SSD1306 (SCL=D1/GPIO5, SDA=D2/GPIO4, addr 0x3C)
#   4. 3x image confirmation + confidence >= 50 ghost-finger filter

from machine import Pin, SoftI2C, PWM, UART
import time
import network
import urequests
import ujson
import ssd1306
from r307 import (
    R307,
    FINGERPRINT_OK,
    FINGERPRINT_NOFINGER,
    FINGERPRINT_ENROLLMISMATCH,
)

# ── Configuration ────────────────────────────────────────────────
WIFI_SSID = "pwm"
WIFI_PASSWORD = "12345678"
SCRIPT_URL = "SCRIPT_URL"

BUZZER_PIN = 0   # D3 (GPIO0)
OLED_SCL = 5     # D1 (GPIO5)
OLED_SDA = 4     # D2 (GPIO4)
OLED_ADDR = 0x3C

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


def get_name_by_id(fid):
    return NAME_MAP.get(fid, "User_%d" % fid)


# ── Buzzer (tuned to 2000-3500 Hz resonant range from bring-up) ──
def _tone(freq, ms):
    b = PWM(Pin(BUZZER_PIN), freq=freq, duty=512)
    time.sleep_ms(ms)
    b.deinit()
    Pin(BUZZER_PIN, Pin.OUT).value(0)


def beep_success():
    for f, ms in ((2000, 150), (2700, 150), (3500, 200)):
        _tone(f, ms)
        time.sleep_ms(30)


def beep_denied():
    _tone(1200, 300)
    time.sleep_ms(50)
    _tone(900, 400)


def beep_startup():
    for f in range(1500, 3501, 250):
        _tone(f, 60)
        time.sleep_ms(15)


def beep_scan():
    _tone(2400, 80)


def beep_enroll():
    _tone(2700, 100)
    time.sleep_ms(30)
    _tone(2700, 100)


# ── OLED UI helpers ──────────────────────────────────────────────
i2c = SoftI2C(scl=Pin(OLED_SCL), sda=Pin(OLED_SDA), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=OLED_ADDR)
oled.contrast(255)


def show_message(line1="", line2="", line3=""):
    oled.fill(0)
    oled.text(str(line1)[:16], 0, 8)
    oled.text(str(line2)[:16], 0, 28)
    oled.text(str(line3)[:16], 0, 48)
    oled.show()


def show_waiting():
    oled.fill(0)
    bx, by = 50, 8
    oled.rect(bx, by, 28, 36, 1)
    oled.hline(bx + 5, by + 10, 18, 1)
    oled.hline(bx + 4, by + 18, 20, 1)
    oled.hline(bx + 5, by + 26, 18, 1)
    oled.text("Place Finger...", 8, 50)
    oled.show()


def show_enroll_waiting(fid, step):
    oled.fill(0)
    oled.rect(0, 0, 128, 64, 1)
    oled.text("-- ENROLL MODE --", 4, 6)
    oled.text("ID:%d  Step:%d/2" % (fid, step), 6, 20)
    oled.text("Place finger..." if step == 1 else "Place SAME fngr", 6, 34)
    oled.text("R#%d to cancel" % fid, 6, 50)
    oled.show()


def show_scan_animation():
    for w in range(16, 113, 24):
        oled.fill(0)
        oled.text("Scanning...", 20, 16)
        oled.rect(14, 36, 100, 12, 1)
        oled.fill_rect(14, 36, w, 12, 1)
        oled.show()
        time.sleep_ms(60)


def show_granted_animation(fid, name):
    oled.fill(1)
    oled.text("MARKED!", 36, 28, 0)
    oled.show()
    time.sleep_ms(300)

    oled.fill(0)
    oled.rect(2, 2, 124, 60, 1)
    oled.rect(4, 4, 120, 56, 1)
    oled.text("MARKED!", 36, 10)
    oled.text("ID  : %d" % fid, 16, 28)
    oled.text("Name: %s" % name[:10], 16, 44)
    oled.show()


def show_denied_animation():
    for _ in range(2):
        oled.fill(1)
        oled.show()
        time.sleep_ms(80)
        oled.fill(0)
        oled.show()
        time.sleep_ms(80)
    oled.fill(0)
    oled.rect(2, 2, 124, 60, 1)
    oled.line(30, 12, 98, 46, 1)
    oled.line(98, 12, 30, 46, 1)
    oled.text("ACCESS DENIED", 12, 50)
    oled.show()


def show_sending_animation():
    for dot in range(1, 4):
        oled.fill(0)
        oled.text("Sending data" + ("." * dot), 12, 20)
        for b in range(4):
            bh = (b + 1) * 6
            bx = 44 + b * 12
            by = 50 - bh
            if b < dot:
                oled.fill_rect(bx, by, 8, bh, 1)
            else:
                oled.rect(bx, by, 8, bh, 1)
        oled.show()
        time.sleep_ms(300)


# ── Ghost-finger filter & scan ───────────────────────────────────
def is_real_finger(finger):
    ok_count = 0
    for _ in range(3):
        p = finger.get_image()
        if p == FINGERPRINT_OK:
            ok_count += 1
        elif p == FINGERPRINT_NOFINGER:
            return False
        time.sleep_ms(20)
    return ok_count >= 3


def get_fingerprint_id(finger):
    if not is_real_finger(finger):
        return -1
    time.sleep_ms(50)
    if finger.get_image() != FINGERPRINT_OK:
        return -1

    beep_scan()
    show_scan_animation()

    if finger.image2tz(1) != FINGERPRINT_OK:
        show_message("Convert Failed", "Try again")
        return -1

    p = finger.finger_fast_search(1)
    if p == FINGERPRINT_OK:
        if finger.confidence < 50:
            return -1
        return finger.finger_id

    time.sleep_ms(100)
    if finger.get_image() == FINGERPRINT_NOFINGER:
        return -1

    beep_denied()
    show_denied_animation()
    t0 = time.ticks_ms()
    while finger.get_image() != FINGERPRINT_NOFINGER and time.ticks_diff(time.ticks_ms(), t0) < 5000:
        time.sleep_ms(50)
    time.sleep_ms(500)
    return -1


# ── Enrollment / Delete / List ───────────────────────────────────
def list_stored_ids(finger):
    finger.get_template_count()
    found = []
    for i in range(1, 128):
        if finger.load_model(i) == FINGERPRINT_OK:
            found.append((i, get_name_by_id(i)))
    oled.fill(0)
    oled.rect(0, 0, 128, 64, 1)
    oled.text("Stored IDs: %d" % len(found), 8, 8)
    for idx, (fid, name) in enumerate(found[:3]):
        oled.text("#%02d %s" % (fid, name[:10]), 8, 22 + idx * 12)
    oled.show()
    time.sleep_ms(3000)
    return found


def remove_fingerprint(finger, fid):
    show_message("Removing...", "ID: %d" % fid, "Please wait")
    if finger.delete_model(fid) == FINGERPRINT_OK:
        show_message("ID REMOVED!", "ID #%d deleted" % fid, get_name_by_id(fid))
    else:
        show_message("Delete Failed!", "ID #%d" % fid, "Not found?")
    beep_denied()
    time.sleep_ms(2000)


def enroll_fingerprint(finger, fid):
    for step in (1, 2):
        show_enroll_waiting(fid, step)
        t0 = time.ticks_ms()
        while finger.get_image() != FINGERPRINT_OK:
            if time.ticks_diff(time.ticks_ms(), t0) > 30000:
                show_message("Timeout!", "Enroll cancelled")
                beep_denied()
                time.sleep_ms(2000)
                return False
            time.sleep_ms(50)

        beep_enroll()
        show_message("Finger Detected", "Processing...")
        if finger.image2tz(step) != FINGERPRINT_OK:
            show_message("Convert Failed", "Try again")
            beep_denied()
            time.sleep_ms(2000)
            return False

        if step == 1:
            show_message("Scan 1 OK!", "Remove finger")
            beep_success()
            time.sleep_ms(1500)
            while finger.get_image() != FINGERPRINT_NOFINGER:
                time.sleep_ms(50)

    show_message("Creating", "Model...")
    p = finger.create_model()
    if p == FINGERPRINT_ENROLLMISMATCH:
        show_message("MISMATCH!", "Use SAME finger", "Try again")
        beep_denied()
        time.sleep_ms(2500)
        return False
    elif p != FINGERPRINT_OK:
        show_message("Model Failed", "Try again")
        beep_denied()
        time.sleep_ms(2000)
        return False

    show_message("Storing...", "ID: %d" % fid)
    if finger.store_model(fid) == FINGERPRINT_OK:
        finger.get_template_count()
        show_message("ENROLLED! #%d" % fid, get_name_by_id(fid), "Total: %d" % finger.template_count)
        beep_success()
        time.sleep_ms(3000)
        return True

    show_message("Store Failed!", "Try again")
    beep_denied()
    time.sleep_ms(2000)
    return False


# ── Wi-Fi & Google Sheets attendance logging ─────────────────────
wlan = network.WLAN(network.STA_IF)


def connect_wifi():
    wlan.active(True)
    if wlan.isconnected():
        return True
    show_message("Connecting WiFi", WIFI_SSID, "Please wait...")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(30):
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            show_message("WiFi Connected!", ip)
            _tone(2500, 300)
            time.sleep_ms(1500)
            return True
        time.sleep_ms(500)
    show_message("WiFi FAILED!", "Check hotspot:", WIFI_SSID)
    beep_denied()
    time.sleep_ms(2000)
    return False


def send_attendance(fid, name):
    show_sending_animation()
    if not wlan.isconnected():
        if not connect_wifi():
            return
    if not SCRIPT_URL or SCRIPT_URL == "SCRIPT_URL":
        show_message("ATTENDANCE OK", "Name: %s" % name[:10], "ID: %d (local)" % fid)
        beep_success()
        time.sleep_ms(2500)
        return
    try:
        payload = ujson.dumps({"id": fid, "name": name, "status": "Present"})
        r = urequests.post(SCRIPT_URL, data=payload, headers={"Content-Type": "application/json"})
        code = r.status_code
        r.close()
        if code in (200, 302):
            show_message("ATTENDANCE SAVED", "Name: %s" % name[:10], "ID:%d Present" % fid)
            beep_success()
        else:
            show_message("Log Failed!", "HTTP: %d" % code, "Try again")
            beep_denied()
    except Exception as e:
        show_message("Log Failed!", str(e)[:16], "Try again")
        beep_denied()
    time.sleep_ms(3000)


# ── Main startup (with 1s sensor boot wait + 30x handshake) ──────
def main():
    Pin(BUZZER_PIN, Pin.OUT).value(0)
    Pin(2, Pin.OUT).value(1)  # on-board LED off

    show_message("ATTEND", "SYSTEM", "Booting...")
    beep_startup()
    time.sleep_ms(1000)  # crucial 1s boot delay for fingerprint sensor

    connect_wifi()

    # Note: on ESP8266 MicroPython, hardware UART0 is swapped to D7(RX)/D8(TX)
    # when talking to the sensor in standalone mode.
    uart = UART(0, baudrate=57600)
    finger = R307(uart)

    ok = 0
    for _ in range(30):
        if finger.verify_password():
            ok += 1
        time.sleep_ms(100)

    if ok == 0:
        show_message("Sensor Error!", "Check wiring")
        beep_denied()
        return

    finger.get_parameters()
    finger.get_template_count()
    show_message("Stored Prints:", str(finger.template_count), "System Ready!")
    time.sleep_ms(2000)

    while True:
        show_waiting()
        fid = get_fingerprint_id(finger)
        if fid > 0:
            name = get_name_by_id(fid)
            show_granted_animation(fid, name)
            time.sleep_ms(500)
            send_attendance(fid, name)
        time.sleep_ms(50)


if __name__ == "__main__":
    main()
