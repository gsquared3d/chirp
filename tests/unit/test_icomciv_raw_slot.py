"""gsquared3d fork: IcomCIVRadio.get_raw_slot / set_raw_slot (W-25, D-135).

A stand-in IC-7000 answers CI-V memory commands (0x1A 0x00) from its own
store, echoing like a CT-17. Records below are real IC-7000 replies (W-25).
"""
import unittest

from chirp.drivers import icomciv
from chirp import errors

# Bank D memory 1 (CHIRP 297) as stored from the front panel: 145.100 FM, skip,
# TX half 145.100, TSQL tones 136.5 (tone mode off).
D01 = bytes.fromhex(
    "040001" "0000001045010501000008850013650000230000104501050100000885"
    "001365000023202020202020202020")
# The same memory rebuilt through set_memory (TX half from the template).
D01_REBUILT = bytes.fromhex(
    "040001" "0000001045010501000008850013650000230000004401050100000885"
    "000885000023202020202020202020")
# Bank A memory 102, the driver's write template ("SCAN EDGE").
TEMPLATE = bytes.fromhex(
    "010102" "000000004401050100000885000885000023000000440105010000088500"
    "0885000023" "5343414e2045444745")


class FakeIC7000:
    def __init__(self):
        self.buf = bytearray()
        self.store = {b"\x01\x01\x02": TEMPLATE}
        self.refuse = set()
        self.wrong_answer = False
        self.baudrate = 19200
        self.timeout = 1

    def write(self, raw):
        raw = bytes(raw)
        self.buf += raw
        if raw[2:4] == b"\xe0\xe0":
            return len(raw)
        data = raw[6:-1]
        key = data[:3]
        if len(data) == 3:
            body = self.store.get(key, key + b"\xff")
            if self.wrong_answer:
                body = b"\x05" + body[1:]
            self.buf += b"\xfe\xfe\xe0\x70\x1a\x00" + body + b"\xfd"
        elif key in self.refuse:
            self.buf += b"\xfe\xfe\xe0\x70\xfa\xfd"
        else:
            if data[3:] == b"\xff":
                self.store.pop(key, None)
            else:
                self.store[key] = data
            self.buf += b"\xfe\xfe\xe0\x70\xfb\xfd"
        return len(raw)

    def read(self, size=1):
        got, self.buf = bytes(self.buf[:size]), self.buf[size:]
        return got


class TestRawSlot(unittest.TestCase):
    def setUp(self):
        self.pipe = FakeIC7000()
        self.radio = icomciv.Icom7000Radio(self.pipe)

    def test_get_raw_slot_returns_the_record_with_its_location(self):
        self.pipe.store[D01[:3]] = D01
        self.assertEqual(self.radio.get_raw_slot(297), D01)

    def test_get_raw_slot_of_an_empty_memory(self):
        self.assertEqual(self.radio.get_raw_slot(2), b"\x01\x00\x03\xff")

    def test_set_raw_slot_puts_back_what_set_memory_cannot(self):
        self.pipe.store[D01[:3]] = D01_REBUILT
        self.radio.set_raw_slot(297, D01)
        self.assertEqual(self.pipe.store[D01[:3]], D01)
        self.assertEqual(self.radio.get_raw_slot(297), D01)

    def test_set_raw_slot_with_an_empty_record_erases(self):
        self.pipe.store[D01[:3]] = D01
        self.radio.set_raw_slot(297, D01[:3] + b"\xff")
        self.assertNotIn(D01[:3], self.pipe.store)

    def test_set_raw_slot_refuses_a_record_for_another_memory(self):
        with self.assertRaises(errors.InvalidDataError):
            self.radio.set_raw_slot(296, D01)
        with self.assertRaises(errors.InvalidDataError):
            self.radio.set_raw_slot(297, D01[:3])

    def test_set_raw_slot_raises_when_the_radio_says_no(self):
        self.pipe.refuse.add(D01[:3])
        with self.assertRaises(errors.RadioError):
            self.radio.set_raw_slot(297, D01)

    def test_get_raw_slot_raises_on_an_answer_for_another_memory(self):
        self.radio.get_raw_slot(0)          # baud detection reads the template
        self.pipe.wrong_answer = True
        with self.assertRaises(errors.RadioError):
            self.radio.get_raw_slot(297)
