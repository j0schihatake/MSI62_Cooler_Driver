"""Optional Cooler Boost controller for ISW (GPL-3.0)."""
import argparse
import configparser
import fcntl
import logging
import math
import signal
import threading
import time
from pathlib import Path


class Controller:
    def __init__(self, on=75, off=65, delay=30, gpu_on=None, gpu_off=None):
        # on/off apply to the CPU; the GPU uses the same pair unless given its own.
        gpu_on = on if gpu_on is None else gpu_on
        gpu_off = off if gpu_off is None else gpu_off
        if (not (1 <= off < on <= 100) or not (1 <= gpu_off < gpu_on <= 100)
                or not math.isfinite(delay) or delay < 0):
            raise ValueError('Require 1 <= off < on <= 100 for CPU and GPU and finite delay >= 0')
        self.on, self.off, self.delay = on, off, delay
        self.gpu_on, self.gpu_off = gpu_on, gpu_off
        self.owned = False
        self.cool_since = None

    def step(self, cpu, gpu, enabled, now):
        if not all(1 <= t <= 125 for t in (cpu, gpu)):
            self.cool_since = None
            raise ValueError('Invalid EC temperature; keeping current boost state')
        if not enabled:
            self.owned = False
            self.cool_since = None
        if cpu >= self.on or gpu >= self.gpu_on:
            self.cool_since = None
            if not enabled:
                return True
        elif self.owned and enabled and cpu <= self.off and gpu <= self.gpu_off:
            if self.cool_since is None:
                self.cool_since = now
            if now - self.cool_since >= self.delay:
                return False
        else:
            self.cool_since = None
        return None

    def committed(self, enabled):
        self.owned = enabled
        self.cool_since = None


class EC:
    def __init__(self, config, path):
        cfg = configparser.ConfigParser()
        with open(config) as source:
            cfg.read_file(source)
        profile = cfg['COOLER_BOOST']['address_profile']
        self.addresses = [int(cfg[profile][key], 16) for key in (
            'realtime_cpu_temp_address', 'realtime_gpu_temp_address', 'cooler_boost_address')]
        if any(not 0 <= a <= 255 for a in self.addresses) or len(set(self.addresses)) != 3:
            raise ValueError('Invalid EC addresses')
        if (cfg.getint('COOLER_BOOST', 'cooler_boost_on'),
                cfg.getint('COOLER_BOOST', 'cooler_boost_off')) != (128, 0):
            raise ValueError('Only the ISW bit-7 Cooler Boost mapping is supported')
        self.path = path

    @staticmethod
    def byte(stream, address):
        stream.seek(address)
        data = stream.read(1)
        if len(data) != 1:
            raise OSError('Short EC read')
        return data[0]

    def read(self):
        with open(self.path, 'rb', buffering=0) as stream:
            cpu, gpu, boost = [self.byte(stream, a) for a in self.addresses]
        return cpu, gpu, bool(boost & 128)

    def write(self, enabled):
        with open(self.path, 'r+b', buffering=0) as stream:
            address = self.addresses[2]
            value = self.byte(stream, address)
            value = value | 128 if enabled else value & 127
            stream.seek(address)
            if stream.write(bytes([value])) != 1:
                raise OSError('Short EC write')
            if bool(self.byte(stream, address) & 128) != enabled:
                raise OSError('Cooler Boost write verification failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Automatic ISW Cooler Boost')
    parser.add_argument('--on', type=int, default=75)
    parser.add_argument('--off', type=int, default=65)
    parser.add_argument('--gpu-on', type=int, help='GPU threshold (default: --on)')
    parser.add_argument('--gpu-off', type=int, help='GPU threshold (default: --off)')
    parser.add_argument('--cool-seconds', type=float, default=30)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--config', default='/etc/isw.conf')
    parser.add_argument('--dry-run', action='store_true', help='Read temperatures without writing EC')
    args = parser.parse_args(argv)
    try:
        control = Controller(args.on, args.off, args.cool_seconds, args.gpu_on, args.gpu_off)
        if not math.isfinite(args.interval) or not 0.2 <= args.interval <= 60:
            raise ValueError('Interval must be 0.2..60 seconds')
        if Path('/sys/class/dmi/id/product_name').read_text().strip() != 'GT62VR 7RE':
            raise ValueError('This controller is restricted to GT62VR 7RE')
        ec = EC(args.config, '/sys/kernel/debug/ec/ec0/io')
    except (ValueError, OSError, configparser.Error, KeyError) as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    # One daemon at a time. Never clear boost at exit or after a sensor error.
    with open('/run/isw-auto-boost.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while not stop.is_set():
            try:
                cpu, gpu, enabled = ec.read()
                action = control.step(cpu, gpu, enabled, time.monotonic())
                if args.dry_run:
                    logging.info('CPU=%s GPU=%s boost=%s decision=%s', cpu, gpu, enabled, action)
                elif action is not None:
                    ec.write(action)
                    control.committed(action)
                    logging.info('Cooler Boost %s; CPU=%s GPU=%s', 'ON' if action else 'OFF', cpu, gpu)
            except (OSError, ValueError) as error:
                control.cool_since = None
                logging.error('%s; no automatic switch-off', error)
            stop.wait(args.interval)


if __name__ == '__main__':
    main()
