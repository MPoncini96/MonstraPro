#!/usr/bin/env bash
# Idempotently installs the goodtft/LCD-show "MHS35" driver for the
# attached 3.5" LCD (kernel devicetree overlay, console/X11 rotation, and
# framebuffer config) and applies this enclosure's rotation correction.
# Automates the previously-manual process:
#
#   cd ~ && git clone https://github.com/goodtft/LCD-show.git
#   cd LCD-show && sudo ./MHS35-show          # installs + reboots
#   sudo ./rotate.sh 180                      # rotation correction, if needed
#
# The upstream MHS35-show installer is an opaque third-party script that
# unconditionally reboots the Pi once it finishes - this wrapper does not
# (and cannot, without patching vendor code) prevent that reboot. What it
# guarantees instead: each step only ever runs once. A marker file is
# written immediately BEFORE invoking a step that might reboot, so if the
# box reboots mid-step, the next boot's re-run of this script (via
# image/systemd/monstrapro-lcd-setup.service) sees the marker and skips
# straight past it - no repeated reboots, no re-running an already-applied
# driver install.
#
# After both steps complete, the LCD is the primary display and HDMI is no
# longer required - see image/README.md "LCD display setup". The physical
# HDMI cable, if any, should be disconnected; nothing in software depends
# on it being present or absent.
#
# Usage (on the target Pi, as root):
#   sudo image/scripts/lcd-setup.sh [--dry-run] [--rotation DEGREES]
#
# Rotation defaults to 180 (this enclosure's requirement) and can be
# overridden with --rotation or the MONSTRAPRO_LCD_ROTATION env var
# (/etc/monstrapro/env - the same override mechanism the systemd units
# already use). Valid values match rotate.sh's own: 0, 90, 180, 270.
#
# Never run this on a non-Linux machine, and never against a real device
# from a development workstation.

set -euo pipefail

DRY_RUN=0
ROTATION="${MONSTRAPRO_LCD_ROTATION:-180}"
VALID_ROTATIONS="0 90 180 270"

VENDOR_DIR="/opt/monstrapro/vendor/LCD-show"
LCD_SHOW_REPO="https://github.com/goodtft/LCD-show.git"
STATE_DIR="/var/lib/monstrapro"
DRIVER_MARKER="$STATE_DIR/.lcd-driver-installed"

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --rotation) ROTATION="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

case " $VALID_ROTATIONS " in
    *" $ROTATION "*) ;;
    *)
        echo "invalid --rotation '$ROTATION' (must be one of: $VALID_ROTATIONS)" >&2
        exit 1
        ;;
esac

# Rotation is folded into the marker's filename, not a single fixed marker -
# switching the configured rotation later (e.g. a support call after the
# enclosure design changes) re-runs only rotate.sh, not the whole driver
# install, and switching back doesn't lose the earlier marker either.
ROTATION_MARKER="$STATE_DIR/.lcd-rotation-$ROTATION"

run() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ $*"
    else
        "$@"
    fi
}

if [ "$(uname -s)" != "Linux" ]; then
    echo "lcd-setup.sh only runs on Linux (the Raspberry Pi target) - refusing to run on $(uname -s)." >&2
    exit 1
fi

if [ "$DRY_RUN" != "1" ] && [ "$(id -u)" != "0" ]; then
    echo "lcd-setup.sh must run as root (installs a kernel devicetree overlay and framebuffer config)." >&2
    echo "Re-run with sudo, or pass --dry-run to preview without executing." >&2
    exit 1
fi

echo "Monstra.Pro Box LCD setup (rotation=$ROTATION, dry_run=$DRY_RUN)"

run mkdir -p "$STATE_DIR"

# --- vendor the driver, only if not already vendored -------------------------
# Normally already present from image/scripts/install.sh's provisioning-time
# clone (so a real customer device never needs internet access just to get
# its display working - see image/README.md "LCD display setup" for why
# that matters here specifically). Cloning it here too keeps this script
# independently runnable/idempotent even outside that flow.
if [ -d "$VENDOR_DIR" ]; then
    echo "LCD-show already vendored at $VENDOR_DIR - skipping clone"
else
    run mkdir -p "$(dirname "$VENDOR_DIR")"
    run git clone --depth 1 "$LCD_SHOW_REPO" "$VENDOR_DIR"
fi

# --- install the driver, exactly once -----------------------------------------
if [ -f "$DRIVER_MARKER" ]; then
    echo "LCD driver already installed (marker present) - skipping MHS35-show"
else
    run touch "$DRIVER_MARKER"
    (
        cd "$VENDOR_DIR"
        run ./MHS35-show
    )
    # MHS35-show reboots unconditionally; on a real (non-dry-run) install,
    # execution never reaches here - the next boot re-runs this script via
    # monstrapro-lcd-setup.service and finds $DRIVER_MARKER already present.
fi

# --- apply the enclosure's rotation, exactly once per rotation value ---------
if [ -f "$ROTATION_MARKER" ]; then
    echo "Rotation $ROTATION already applied (marker present) - skipping rotate.sh"
else
    run touch "$ROTATION_MARKER"
    (
        cd "$VENDOR_DIR"
        run ./rotate.sh "$ROTATION"
    )
fi

echo "LCD setup complete. The 3.5in LCD is the primary display; HDMI is not required."
