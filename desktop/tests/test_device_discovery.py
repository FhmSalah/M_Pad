"""Serial discovery regressions using mocks only; no Qt or device access."""

import itertools
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import detect_device as device


def port(name, vid=None, pid=None):
    return SimpleNamespace(device=name, vid=vid, pid=pid)


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.ports = self.enterContext(patch.object(device.list_ports, "comports", return_value=[]))
        self.serial = self.enterContext(patch.object(
            device.serial, "Serial", side_effect=AssertionError("unexpected serial access")))
        self.enterContext(patch.object(device.sys, "platform", "darwin"))

    def probe_order(self, candidates):
        self.ports.return_value = candidates
        with patch.object(device, "open_macro_pad", return_value=None) as probe:
            self.assertIsNone(device.find_macro_pad())
        return [entry.args[0] for entry in probe.call_args_list]

    def test_macos_filters_missing_vid_or_pid_only(self):
        candidates = [port("bluetooth"), port("missing-pid", 0x303A),
                      port("missing-vid", pid=0x1001), port("usb-other", 1, 2),
                      port("usb-zero", 0, 0)]
        self.assertEqual(self.probe_order(candidates), ["usb-other", "usb-zero"])

    def test_macos_priority_and_stable_order_within_each_tier(self):
        candidates = [port("other-one", 1, 2), port("/dev/cu.usbmodemA", 3, 4),
                      port("esp-one", 0x303A, 0x1001), port("bluetooth"),
                      port("other-two", 0x303A, 0x9999),
                      port("/dev/cu.usbmodemB", 0x303A, 0x9999),
                      port("esp-two", 0x303A, 0x1001)]
        self.assertEqual(self.probe_order(candidates),
                         ["esp-one", "esp-two", "/dev/cu.usbmodemA",
                          "/dev/cu.usbmodemB", "other-one", "other-two"])

    def test_windows_keeps_all_candidates_in_original_order(self):
        candidates = [port("COM1"), port("COM2", 1, None),
                      port("COM3", 1, 2), port("COM4", 0x303A, 0x1001)]
        with patch.object(device.sys, "platform", "win32"):
            self.assertEqual(self.probe_order(candidates), ["COM1", "COM2", "COM3", "COM4"])

    def test_discovery_reenumerates_changing_device_paths(self):
        self.ports.side_effect = [[port("/dev/cu.usbmodemOLD", 0x303A, 0x1001)],
                                  [port("/dev/cu.usbmodemNEW", 0x303A, 0x1001)]]
        first, second = object(), object()
        with patch.object(device, "open_macro_pad", side_effect=[first, second]) as probe:
            self.assertIs(device.find_macro_pad(), first)
            self.assertIs(device.find_macro_pad(), second)
        self.assertEqual(probe.call_args_list,
                         [call("/dev/cu.usbmodemOLD", None), call("/dev/cu.usbmodemNEW", None)])
        self.assertEqual(self.ports.call_count, 2)

    def test_each_attempt_uses_existing_handshake_even_for_preferred_vid_pid(self):
        self.ports.return_value = [port("esp-first", 0x303A, 0x1001),
                                  port("usb-fallback", 1, 2)]
        rejected, accepted = Mock(), Mock()
        self.serial.side_effect = [rejected, accepted]
        stop = Event()
        with patch.object(device, "handshake", side_effect=[False, True]) as handshake:
            self.assertIs(device.find_macro_pad(stop), accepted)
        self.assertEqual(handshake.call_args_list, [call(rejected, stop), call(accepted, stop)])
        rejected.close.assert_called_once_with()
        accepted.close.assert_not_called()
        self.assertEqual(self.serial.call_args_list, [
            call(name, baudrate=115200, timeout=0.1, write_timeout=0.2)
            for name in ("esp-first", "usb-fallback")])

    def test_real_handshake_rejects_wrong_identity_then_accepts_exact_response(self):
        self.ports.return_value = [port("esp-wrong", 0x303A, 0x1001),
                                  port("esp-correct", 0x303A, 0x1001)]
        rejected, accepted = Mock(), Mock()
        for connection, response in ((rejected, b"MACROPAD:V2\n"),
                                     (accepted, b"MACROPAD:V1\r\n")):
            stream = iter(bytes([value]) for value in response)
            connection.read.side_effect = lambda size, stream=stream: next(stream, b"")
        self.serial.side_effect = [rejected, accepted]
        ticks = itertools.count()
        with patch.object(device.time, "monotonic", side_effect=lambda: next(ticks) * 0.01):
            self.assertIs(device.find_macro_pad(), accepted)
        rejected.close.assert_called_once_with()
        accepted.close.assert_not_called()
        for connection in (rejected, accepted):
            self.assertTrue(connection.write.called)
            self.assertTrue(all(entry == call(b"WHO\n") for entry in connection.write.call_args_list))
        self.assertEqual(device.DETECTION_SECONDS, 3.5)
        self.assertEqual(device.RETRY_SECONDS, 0.4)

    def test_stop_prevents_candidate_opening(self):
        self.ports.return_value = [port("esp", 0x303A, 0x1001)]
        stop = Event()
        stop.set()
        with patch.object(device, "open_macro_pad") as probe:
            self.assertIsNone(device.find_macro_pad(stop))
            probe.assert_not_called()

    def test_enumeration_failure_returns_none(self):
        self.ports.side_effect = OSError("enumeration failed")
        self.assertIsNone(device.find_macro_pad())
        self.serial.assert_not_called()


if __name__ == "__main__":
    unittest.main()
