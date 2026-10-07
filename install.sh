#!/usr/bin/env bash
# Installs isw (MSI EC fan control) with the profile already tuned for this
# laptop: MSI GT62VR 7RE / board MS-16L2 -> EC profile "16L2EMS1_LLM"
# (smooth curve for long GPU loads) plus the automatic Cooler Boost daemon.
#
# Usage:
#   ./install.sh              # install + enable + apply profile 16L2EMS1_LLM
#   ./install.sh 16L2EMS1     # stock MSI curve for this laptop
#   ./install.sh 16J9EMS1     # install but use a different profile
#
# Must be run with sudo/root.

set -euo pipefail

PROFILE="${1:-16L2EMS1_LLM}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
	echo "Run this with sudo: sudo ./install.sh" >&2
	exit 1
fi

echo "==> Installing isw binary to /usr/bin/isw"
install -m 755 "$SRC_DIR/bin/isw" /usr/bin/isw

echo "==> Installing EC profile config to /etc/isw.conf"
install -m 644 "$SRC_DIR/conf/isw.conf" /etc/isw.conf

echo "==> Installing systemd unit template"
install -m 644 "$SRC_DIR/systemd/isw@.service" /etc/systemd/system/isw@.service

echo "==> Enabling ec_sys with write support (needed for isw to read/write EC)"
install -m 644 "$SRC_DIR/modprobe.d/isw-ec_sys.conf" /etc/modprobe.d/isw-ec_sys.conf
install -m 644 "$SRC_DIR/modules-load.d/isw-ec_sys.conf" /etc/modules-load.d/isw-ec_sys.conf
modprobe -r ec_sys 2>/dev/null || true
modprobe ec_sys write_support=1

echo "==> Reloading systemd and enabling isw@${PROFILE}.service"
systemctl daemon-reload
# Disable any other previously-enabled isw@ instance so only one profile is active.
for unit in /etc/systemd/system/multi-user.target.wants/isw@*.service \
            /etc/systemd/system/sleep.target.wants/isw@*.service; do
	[[ -e "$unit" ]] || continue
	name="$(basename "$unit")"
	[[ "$name" == "isw@${PROFILE}.service" ]] || systemctl disable --now "$name" || true
done
systemctl enable "isw@${PROFILE}.service"

echo "==> Applying profile ${PROFILE} to the EC now"
/usr/bin/isw -w "$PROFILE"

# The Cooler Boost daemon refuses to run on any other model.
if [[ "$(cat /sys/class/dmi/id/product_name)" == "GT62VR 7RE" ]]; then
	echo "==> Installing automatic Cooler Boost (CPU 90/80 °C, GPU 82/72 °C)"
	install -d -m 755 /usr/local/lib/isw-auto
	install -m 644 "$SRC_DIR/bin/isw" "$SRC_DIR/auto-boost/isw_auto.py" /usr/local/lib/isw-auto/
	install -m 644 "$SRC_DIR/systemd/isw-auto-boost.service" /etc/systemd/system/isw-auto-boost.service
	systemctl daemon-reload
	systemctl enable isw-auto-boost.service
	systemctl restart isw-auto-boost.service
	# The daemon only switches off a boost it turned on itself.
	/usr/bin/isw -b off
else
	echo "==> Skipping automatic Cooler Boost: it is restricted to GT62VR 7RE"
fi

echo
echo "Done. Active profile: ${PROFILE}"
echo "Check anytime with: sudo isw -p ${PROFILE}"
echo "Live temps/fan speed: sudo isw -r"
