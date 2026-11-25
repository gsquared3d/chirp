"""gsquared3d fork: CI-V traffic the driver didn't ask for, and early read
timeouts (ham-radio-coordinator PROG-041).

With CI-V Transceive on, an Icom radio announces every dial change on the
cable, addressed to everyone (0x00). The driver must skip those instead of
taking one as the answer to its request. Reads that time out in the first
seconds after the port opens (seen on the CT-17) are sent again; writes never
are. Uses the stand-in IC-7000 and real records from test_icomciv_raw_slot.
"""
import unittest

from chirp.drivers import icomciv
from chirp import errors
from tests.unit.test_icomciv_raw_slot import D01, FakeIC7000

# What the IC-7000 sends by itself when the dial moves (Transceive on):
# frequency 145.100 MHz (command 0x00) and mode FM (command 0x01), to 0x00.
TRANSCEIVE_FREQ = b"\xfe\xfe\x00\x70\x00\x00\x00\x10\x45\x01\xfd"
TRANSCEIVE_MODE = b"\xfe\xfe\x00\x70\x01\x05\x01\xfd"


class ChattyIC7000(FakeIC7000):
    """FakeIC7000 that can put unasked frames before a reply, or leave a
    reply out (the radio said nothing before the timeout)."""

    def __init__(self):
        super().__init__()
        self.chatter = []        # frames sent before the next reply
        self.silent = 0          # how many replies to leave out
        self.requests = []       # every request, as sent

    def write(self, raw):
        raw = bytes(raw)
        start = len(self.buf)
        super().write(raw)
        if raw[2:4] == b"\xe0\xe0":           # interface echo test
            return len(raw)
        self.requests.append(raw)
        echo_end = start + len(raw)
        reply = bytes(self.buf[echo_end:])
        del self.buf[echo_end:]
        self.buf += b"".join(self.chatter)
        self.chatter = []
        if self.silent:                       # announcements, then nothing
            self.silent -= 1
            return len(raw)
        self.buf += reply
        return len(raw)


class TestUnaskedTraffic(unittest.TestCase):
    def setUp(self):
        self.pipe = ChattyIC7000()
        self.pipe.store[D01[:3]] = D01
        self.radio = icomciv.Icom7000Radio(self.pipe)
        self.radio.get_raw_slot(0)        # baud detection reads the template

    def test_dial_announcements_before_the_reply_are_skipped(self):
        self.pipe.chatter = [TRANSCEIVE_FREQ, TRANSCEIVE_MODE, TRANSCEIVE_FREQ]
        self.assertEqual(self.radio.get_raw_slot(297), D01)

    def test_announcements_before_a_write_reply_are_skipped(self):
        self.pipe.chatter = [TRANSCEIVE_MODE]
        self.radio.set_raw_slot(297, D01)           # raises unless FB
        self.assertEqual(self.pipe.store[D01[:3]], D01)

    def test_a_radio_that_never_stops_announcing_fails(self):
        self.pipe.chatter = [TRANSCEIVE_FREQ] * (icomciv.MAX_UNASKED_FRAMES + 1)
        with self.assertRaises(errors.RadioError):
            self.radio.get_raw_slot(297)


class TestEarlyTimeouts(unittest.TestCase):
    def setUp(self):
        self.pipe = ChattyIC7000()
        self.pipe.store[D01[:3]] = D01
        self.radio = icomciv.Icom7000Radio(self.pipe)
        self.radio.get_raw_slot(0)

    def _sent_for(self, n_before):
        return self.pipe.requests[n_before:]

    def test_an_early_read_timeout_is_sent_again(self):
        before = len(self.pipe.requests)
        self.pipe.silent = 1
        self.assertEqual(self.radio.get_raw_slot(297), D01)
        sent = self._sent_for(before)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], sent[1])          # the same request, again

    def test_the_retry_is_the_request_not_what_was_read_since(self):
        before = len(self.pipe.requests)
        # An announcement is read into the request's frame, then the radio
        # goes quiet: the retry must still be our memory read.
        self.pipe.chatter = [TRANSCEIVE_FREQ]
        self.pipe.silent = 1
        self.assertEqual(self.radio.get_raw_slot(297), D01)
        sent = self._sent_for(before)
        self.assertEqual(sent[0], sent[1])

    def test_reads_are_retried_at_most_twice(self):
        self.pipe.silent = icomciv.EARLY_RETRIES + 1
        with self.assertRaises(icomciv.CIVTimeout):
            self.radio.get_raw_slot(297)

    def test_a_late_read_timeout_is_not_retried(self):
        self.radio._opened_at -= icomciv.EARLY_WINDOW_S + 1
        before = len(self.pipe.requests)
        self.pipe.silent = 1
        with self.assertRaises(icomciv.CIVTimeout):
            self.radio.get_raw_slot(297)
        self.assertEqual(len(self._sent_for(before)), 1)

    def test_a_write_is_never_sent_twice(self):
        before = len(self.pipe.requests)
        self.pipe.silent = 1
        with self.assertRaises(errors.RadioError):
            self.radio.set_raw_slot(297, D01)
        self.assertEqual(len(self._sent_for(before)), 1)

    def test_timeouts_are_still_radio_errors(self):
        self.assertTrue(issubclass(icomciv.CIVTimeout, errors.RadioError))
