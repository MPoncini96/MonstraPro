#!/usr/bin/env bash
# Runs once on the device's actual first power-on, via
# image/systemd/monstrapro-firstboot.service (ConditionPathExists guards
# against re-running once the marker file exists). Deliberately minimal:
# base Raspberry Pi OS chores (rootfs resize, hostname, SSH host keys) are
# already handled by raspi-config's own first-boot mechanism and are not
# reimplemented here. This script's only job is making sure the
# non-root `monstrapro` user can actually write where it needs to before
# monstrapro-agent/display/worker start - see image/README.md "Boot order".

set -euo pipefail

MARKER=/var/lib/monstrapro/.firstboot-complete

if [ -f "$MARKER" ]; then
    exit 0
fi

mkdir -p /var/lib/monstrapro /opt/monstrapro/releases
chown -R monstrapro:monstrapro /var/lib/monstrapro /opt/monstrapro/releases

touch "$MARKER"
chown monstrapro:monstrapro "$MARKER"
