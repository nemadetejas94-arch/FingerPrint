# Bring-up test for FingerAttend wiring (ESP8266 NodeMCU)
# OLED SSD1306: SCL=D1(GPIO5), SDA=D2(GPIO4), addr 0x3C
# Passive buzzer: D3(GPIO0)
from machine import Pin, SoftI2C, PWM
import time

BUZZER = 0      # D3
SCL, SDA = 5, 4 # D1, D2


def beep(freq=1000, ms=150):
    b = PWM(Pin(BUZZER), freq=freq, duty=512)
    time.sleep_ms(ms)
    b.deinit()
    Pin(BUZZER, Pin.OUT).value(1)  # keep GPIO0 high (boot strap pin)


print("== FingerAttend bring-up ==")

i2c = SoftI2C(scl=Pin(SCL), sda=Pin(SDA), freq=400000)
found = i2c.scan()
print("I2C devices:", [hex(a) for a in found])

oled = None
addr = 0x3C if 0x3C in found else (0x3D if 0x3D in found else None)
if addr is None:
    print("OLED: NOT FOUND (check D1/D2, VCC, GND)")
else:
    import ssd1306
    oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=addr)
    oled.contrast(255)
    oled.fill(0)
    oled.rect(0, 0, 128, 64, 1)
    oled.text("FingerAttend", 16, 6)
    oled.hline(4, 18, 120, 1)
    oled.text("Bring-up OK", 20, 26)
    oled.text("OLED  : 0x%02X" % addr, 8, 40)
    oled.text("Buzzer: D3", 8, 50)
    oled.show()
    print("OLED: OK at", hex(addr))

print("Buzzer: playing tones")
for f in (2000, 2700, 3500):  # near passive-buzzer resonance = loudest
    beep(f, 250)
    time.sleep_ms(30)
print("Buzzer: done")
print("== bring-up complete ==")
