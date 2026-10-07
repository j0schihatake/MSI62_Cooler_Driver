import tempfile
import unittest
from pathlib import Path
from isw_auto import Controller, EC


class AutoTests(unittest.TestCase):
    def test_either_sensor_triggers(self):
        for temps in ((75, 60), (60, 75)):
            c = Controller()
            self.assertIs(c.step(*temps, False, 0), True)

    def test_hysteresis_and_continuous_cooling(self):
        c = Controller()
        c.committed(True)
        self.assertIsNone(c.step(65, 65, True, 0))
        self.assertIsNone(c.step(65, 66, True, 29))
        self.assertIsNone(c.step(65, 65, True, 30))
        self.assertIsNone(c.step(65, 65, True, 59))
        self.assertIs(c.step(65, 65, True, 60), False)

    def test_manual_boost_preserved(self):
        c = Controller()
        self.assertIsNone(c.step(90, 90, True, 0))
        self.assertIsNone(c.step(60, 60, True, 100))
        self.assertIsNone(c.step(60, 60, True, 200))

    def test_sensor_error_resets_timer(self):
        c = Controller()
        c.committed(True)
        c.step(60, 60, True, 0)
        with self.assertRaises(ValueError):
            c.step(0, 60, True, 30)
        self.assertIsNone(c.step(60, 60, True, 60))

    def test_manual_off_reenabled_when_hot(self):
        c = Controller()
        c.committed(True)
        self.assertIs(c.step(90, 60, False, 0), True)

    def test_separate_gpu_thresholds(self):
        c = Controller(90, 80, 60, 82, 72)
        self.assertIsNone(c.step(85, 75, False, 0))
        self.assertIs(c.step(70, 82, False, 0), True)
        self.assertIs(c.step(90, 60, False, 0), True)
        c.committed(True)
        self.assertIsNone(c.step(78, 74, True, 0))
        self.assertIsNone(c.step(78, 72, True, 10))
        self.assertIsNone(c.step(81, 70, True, 70))
        self.assertIsNone(c.step(80, 72, True, 80))
        self.assertIs(c.step(80, 72, True, 140), False)

    def test_validation(self):
        for args in ((75, 85, 30), (85, 75, -1), (85, 75, float('nan')),
                     (85, 75, 30, 70, 80), (85, 75, 30, 101, 70)):
            with self.assertRaises(ValueError):
                Controller(*args)

    def test_ec_preserves_other_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ec'
            data = bytearray(256)
            data[0x68], data[0x80], data[0x98] = 85, 65, 0x35
            path.write_bytes(data)
            ec = EC(Path(__file__).resolve().parents[2] / 'conf/isw.conf', path)
            self.assertEqual(ec.read(), (85, 65, False))
            ec.write(True)
            self.assertEqual(path.read_bytes()[0x98], 0xb5)
            ec.write(False)
            self.assertEqual(path.read_bytes(), data)
            path.write_bytes(b'')
            with self.assertRaises(OSError):
                ec.read()


if __name__ == '__main__':
    unittest.main()
