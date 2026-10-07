# CoolerDriver

Fan control setup for **MSI GT62VR 7RE** (motherboard `MS-16L2`), based on
[isw](https://github.com/YoyPa/isw) — a tool that reads/writes the MSI
embedded controller (EC) directly to control fan curves, CoolerBoost,
battery charge threshold, etc.

This repo is a ready-to-apply snapshot: the EC profile section
**`16L2EMS1`** in `conf/isw.conf` is the correct one for this laptop
(comment in the file: `GT62_6RD GT62_6RE GT62_7RD GT62_7RE`). Just run the
installer — no need to figure out which of the ~35 profiles in `isw.conf`
matches your hardware.

## Why this exists

By default, nothing in `isw` picks the right profile for you — you enable a
specific systemd instance (`isw@<PROFILE>.service`) yourself, and it's easy
to enable the wrong one. On this machine the wrong profile
(`16J9EMS1`, meant for GE62/GF62/GL62/GP62/GV62/PE60/PE62) was enabled by
mistake, which capped the GPU fan at 86% and idle-stopped it at 0%, instead
of the correct curve that ramps to 100%. This repo pins the correct one so a
fresh install doesn't repeat that mistake.

## Install (fresh Linux install)

```
sudo ./install.sh
```

This will:
1. Install `bin/isw` to `/usr/bin/isw`
2. Install `conf/isw.conf` to `/etc/isw.conf`
3. Install the systemd unit template to `/etc/systemd/system/isw@.service`
4. Enable the `ec_sys` kernel module with `write_support=1`
   (`modprobe.d`/`modules-load.d` files), required for isw to write to the EC
5. Enable and start `isw@16L2EMS1_LLM.service` (runs on boot and on
   resume-from-sleep, via `multi-user.target` + `sleep.target`)
6. Apply the `16L2EMS1_LLM` profile to the EC immediately, so you don't have to
   reboot to get correct fan behavior
7. On a GT62VR 7RE only: install and enable `isw-auto-boost.service`
   (automatic Cooler Boost, see below)

To get the stock MSI curve instead: `sudo ./install.sh 16L2EMS1`.

## Profile `16L2EMS1_LLM`

A copy of `16L2EMS1` tuned for long GPU loads (local LLMs in Ollama): the
middle of the curve is raised so the fans run steadily at ~50–65 % instead of
the stock curve leaving the CPU fan at 54 % even at 97 °C and relying on
Cooler Boost (100 %) for hours. Less bearing wear and noise, same cooling.

| CPU °C | 52 | 64 | 72 | 80 | 86 | 92 |
|---|---|---|---|---|---|---|
| CPU fan % (stock → LLM) | 26 → 30 | 34 → 40 | 39 → 50 | 43 → 62 | 47 → 75 | 54 → 90 |

| GPU °C | 55 | 62 | 68 | 74 | 80 | 86 |
|---|---|---|---|---|---|---|
| GPU fan % (LLM) | 39 | 47 | 56 | 66 | 80 | 100 |

## Automatic Cooler Boost

`auto-boost/isw_auto.py` (run as `isw --auto-boost`) polls EC temperatures and
uses Cooler Boost only as an emergency, with separate thresholds per chip:

| | Boost ON at | Boost OFF when both are at or below, for 60 s |
|---|---|---|
| GPU | 82 °C | 72 °C |
| CPU | 90 °C | 80 °C |

The GPU limit is lower on purpose: the GTX 1070 starts throttling at 91 °C.
Thresholds are in `systemd/isw-auto-boost.service`
(`--on/--off` = CPU, `--gpu-on/--gpu-off` = GPU; without the GPU flags the
CPU pair applies to both). The daemon never switches off a boost it did not
switch on itself (manual button press), and never clears boost on exit or
sensor error.

Tests: `cd auto-boost && python3 -m unittest discover -s tests`

## Rollback

```
sudo isw -w 16L2EMS1
sudo systemctl disable --now isw-auto-boost.service isw@16L2EMS1_LLM.service
sudo systemctl enable isw@16L2EMS1.service
sudo isw -b off
```

If you ever install this on a *different* MSI laptop, pass the matching
profile name from `conf/isw.conf` instead:

```
sudo ./install.sh <PROFILE_NAME>
```

(Find your board name with `cat /sys/class/dmi/id/board_name`, then
`grep -B2 <that name>` in `conf/isw.conf` to find the matching section — the
comments above each `[SECTION]` list the model names/board names it covers.)

## Verify

```
sudo isw -p 16L2EMS1_LLM # dump the profile currently loaded in isw.conf and compare to EC
sudo isw -r               # live CPU/GPU temp + fan speed + RPM
sudo systemctl status isw@16L2EMS1_LLM.service isw-auto-boost.service
journalctl -u isw-auto-boost.service   # every Cooler Boost ON/OFF with temps
```

## Files

| Path | Installed to | Purpose |
|---|---|---|
| `bin/isw` | `/usr/bin/isw`, `/usr/local/lib/isw-auto/` | The EC read/write tool (Python 3), plus `--auto-boost` |
| `auto-boost/isw_auto.py` | `/usr/local/lib/isw-auto/` | Automatic Cooler Boost controller |
| `conf/isw.conf` | `/etc/isw.conf` | All known MSI EC profiles, incl. `16L2EMS1` and `16L2EMS1_LLM` for this laptop |
| `systemd/isw@.service` | `/etc/systemd/system/isw@.service` | Oneshot service, applies profile `%I` on boot/resume |
| `systemd/isw-auto-boost.service` | `/etc/systemd/system/` | Cooler Boost daemon with the thresholds above |
| `modprobe.d/isw-ec_sys.conf` | `/etc/modprobe.d/` | Loads `ec_sys` with `write_support=1` |
| `modules-load.d/isw-ec_sys.conf` | `/etc/modules-load.d/` | Autoloads `ec_sys` at boot |

## Notes

- The EC forgets manual writes on reboot or when the power source changes —
  that's exactly why the systemd service re-applies the profile on every
  boot and wake.
- `isw` requires kernel support for `/sys/kernel/debug/ec/ec0/io`
  (`debugfs` mounted, which is standard on Ubuntu/Debian kernels) plus the
  `ec_sys` module loaded with write support.
- Upstream project: <https://github.com/YoyPa/isw> (GPLv3, see `LICENSE`).
  This repo adds the installer, pins the right profile for this laptop, adds
  the `16L2EMS1_LLM` section to `isw.conf` and the `--auto-boost` entry point
  (5 lines at the end of `bin/isw`); the rest is unmodified upstream.
