# R307 / AS608 Optical Fingerprint Sensor Driver (MicroPython / Python)
# Implements the ZFM-20 / Synochip packet protocol used by Adafruit_Fingerprint.

import time

FINGERPRINT_OK = 0x00
FINGERPRINT_PACKETRECIEVEERR = 0x01
FINGERPRINT_NOFINGER = 0x02
FINGERPRINT_IMAGEFAIL = 0x03
FINGERPRINT_IMAGEMESS = 0x06
FINGERPRINT_FEATUREFAIL = 0x07
FINGERPRINT_NOMATCH = 0x08
FINGERPRINT_NOTFOUND = 0x09
FINGERPRINT_ENROLLMISMATCH = 0x0A
FINGERPRINT_BADLOCATION = 0x0B

_STARTCODE = 0xEF01
_COMMANDPACKET = 0x01
_ACKPACKET = 0x07


class R307:
    def __init__(self, uart, address=0xFFFFFFFF, password=0x00000000):
        self.uart = uart
        self.address = address
        self.password = password
        self.finger_id = 0
        self.confidence = 0
        self.template_count = 0
        self.capacity = 0
        self.security_level = 0
        self.packet_len = 128

    def _sleep_ms(self, ms):
        if hasattr(time, "sleep_ms"):
            time.sleep_ms(ms)
        else:
            time.sleep(ms / 1000.0)

    def _ticks_ms(self):
        if hasattr(time, "ticks_ms"):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _ticks_diff(self, a, b):
        if hasattr(time, "ticks_diff"):
            return time.ticks_diff(a, b)
        return a - b

    def _write_packet(self, payload):
        length = len(payload) + 2
        header = bytearray([
            (_STARTCODE >> 8) & 0xFF, _STARTCODE & 0xFF,
            (self.address >> 24) & 0xFF, (self.address >> 16) & 0xFF,
            (self.address >> 8) & 0xFF, self.address & 0xFF,
            _COMMANDPACKET,
            (length >> 8) & 0xFF, length & 0xFF,
        ])
        checksum = _COMMANDPACKET + ((length >> 8) & 0xFF) + (length & 0xFF)
        for b in payload:
            checksum += b
        checksum &= 0xFFFF
        pkt = header + bytearray(payload) + bytearray([(checksum >> 8) & 0xFF, checksum & 0xFF])
        # Drain stale RX bytes
        while self.uart.any():
            self.uart.read()
        self.uart.write(pkt)

    def _read_packet(self, timeout_ms=1000):
        start = self._ticks_ms()
        buf = bytearray()
        expected_len = None
        while self._ticks_diff(self._ticks_ms(), start) < timeout_ms:
            if self.uart.any():
                chunk = self.uart.read()
                if chunk:
                    buf.extend(chunk)
                    # Sync to 0xEF 0x01 header
                    while len(buf) >= 2 and (buf[0] != 0xEF or buf[1] != 0x01):
                        buf = buf[1:]
                    if expected_len is None and len(buf) >= 9:
                        plen = (buf[7] << 8) | buf[8]
                        expected_len = 9 + plen
                    if expected_len is not None and len(buf) >= expected_len:
                        pkt = buf[:expected_len]
                        ptype = pkt[6]
                        data = pkt[9:-2]
                        return ptype, data
            self._sleep_ms(5)
        return None, None

    def _send_cmd(self, cmd_bytes, timeout_ms=1000):
        self._write_packet(cmd_bytes)
        ptype, data = self._read_packet(timeout_ms)
        if ptype != _ACKPACKET or not data:
            return FINGERPRINT_PACKETRECIEVEERR, b""
        return data[0], data[1:]

    def verify_password(self):
        pw = [
            0x13,
            (self.password >> 24) & 0xFF,
            (self.password >> 16) & 0xFF,
            (self.password >> 8) & 0xFF,
            self.password & 0xFF,
        ]
        code, _ = self._send_cmd(pw, timeout_ms=500)
        return code == FINGERPRINT_OK

    def get_parameters(self):
        code, rest = self._send_cmd([0x0F])
        if code == FINGERPRINT_OK and len(rest) >= 16:
            self.security_level = (rest[2] << 8) | rest[3]
            self.capacity = (rest[4] << 8) | rest[5]
            pkt_code = (rest[12] << 8) | rest[13]
            self.packet_len = 32 * (1 << pkt_code) if pkt_code <= 3 else 128
        return code

    def get_template_count(self):
        code, rest = self._send_cmd([0x1D])
        if code == FINGERPRINT_OK and len(rest) >= 2:
            self.template_count = (rest[0] << 8) | rest[1]
        return code

    def get_image(self):
        code, _ = self._send_cmd([0x01])
        return code

    def image2tz(self, slot=1):
        code, _ = self._send_cmd([0x02, slot & 0xFF])
        return code

    def create_model(self):
        code, _ = self._send_cmd([0x05])
        return code

    def store_model(self, location, slot=1):
        code, _ = self._send_cmd([0x06, slot & 0xFF, (location >> 8) & 0xFF, location & 0xFF])
        return code

    def load_model(self, location, slot=1):
        code, _ = self._send_cmd([0x07, slot & 0xFF, (location >> 8) & 0xFF, location & 0xFF])
        return code

    def delete_model(self, location, count=1):
        code, _ = self._send_cmd([0x0C, (location >> 8) & 0xFF, location & 0xFF, (count >> 8) & 0xFF, count & 0xFF])
        return code

    def empty_database(self):
        code, _ = self._send_cmd([0x0D])
        return code

    def finger_fast_search(self, slot=1, start_page=0x0000, page_num=0x03E8):
        code, rest = self._send_cmd([
            0x1B, slot & 0xFF,
            (start_page >> 8) & 0xFF, start_page & 0xFF,
            (page_num >> 8) & 0xFF, page_num & 0xFF,
        ])
        if code == FINGERPRINT_OK and len(rest) >= 4:
            self.finger_id = (rest[0] << 8) | rest[1]
            self.confidence = (rest[2] << 8) | rest[3]
        return code

    def finger_search(self, slot=1, start_page=0x0000, page_num=0x03E8):
        code, rest = self._send_cmd([
            0x04, slot & 0xFF,
            (start_page >> 8) & 0xFF, start_page & 0xFF,
            (page_num >> 8) & 0xFF, page_num & 0xFF,
        ])
        if code == FINGERPRINT_OK and len(rest) >= 4:
            self.finger_id = (rest[0] << 8) | rest[1]
            self.confidence = (rest[2] << 8) | rest[3]
        return code
