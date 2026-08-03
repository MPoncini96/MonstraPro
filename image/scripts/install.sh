#!/usr/bin/env bash
# Provisions a Raspberry Pi OS Lite (or any systemd Linux) host to run
# Monstra.Pro Box: creates the `monstrapro` user, the /opt + /var/lib +
# /etc directory layout, a first release under /opt/monstrapro/releases/,
# per-service venvs, the systemd units, and the setup.monstra dnsmasq
# override. See image/README.md for the full picture and what this script
# deliberately does NOT do yet (build a real signed release artifact,
# apply NetworkManager/systemctl polkit rules).
#
# Usage (on the target Linux host, as root):
#   sudo image/scripts/install.sh [--dry-run] [--version VERSION]
#
# Never run this on a non-Linux machine or without --dry-run reviewing it
# first - it creates system users, writes to /etc and /opt, and enables
# systemd units.

set -euo pipefail

DRY_RUN=0
VERSION="${MONSTRAPRO_VERSION:-0.0.0-local}"

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --version) VERSION="$2"; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 1 ;;
    esac
done

run() {
    if [ "$DRY_RUN" = "1" ]; then
        echo "+ $*"
    else
        "$@"
    fi
}

if [ "$(uname -s)" != "Linux" ]; then
    echo "install.sh only runs on Linux (the Raspberry Pi 5 target) - refusing to run on $(uname -s)." >&2
    exit 1
fi

if [ "$DRY_RUN" != "1" ] && [ "$(id -u)" != "0" ]; then
    echo "install.sh must run as root (creates system users, /etc and /opt paths, systemd units)." >&2
    echo "Re-run with sudo, or pass --dry-run to preview without executing." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RELEASE_ROOT="/opt/monstrapro/releases/$VERSION"

echo "Installing Monstra.Pro Box (version=$VERSION, dry_run=$DRY_RUN)"

# --- system user -----------------------------------------------------------
if ! id monstrapro >/dev/null 2>&1; then
    run groupadd --system monstrapro
    run useradd --system --gid monstrapro --home-dir /var/lib/monstrapro \
        --shell /usr/sbin/nologin --groups netdev,video monstrapro
fi
# Re-applied unconditionally (not just inside the ! id check above) so a
# re-install on an already-provisioned device also gets this - useradd's
# --groups only takes effect at first creation. `video` group membership is
# required for display.framebuffer.FramebufferWriter to open /dev/fb0
# (root:video, mode 660) - caught live on real Pi 5 hardware: the display
# service could start and run without crashing while never actually being
# able to open the framebuffer device at all.
run usermod -aG video monstrapro

# --- directory layout --------------------------------------------------------
run mkdir -p /opt/monstrapro/releases /var/lib/monstrapro /etc/monstrapro
run mkdir -p "$RELEASE_ROOT"

# --- copy this release's source into place -----------------------------------
for dir in packages services image; do
    run rsync -a --delete \
        --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' --exclude '*.egg-info' \
        "$REPO_ROOT/$dir" "$RELEASE_ROOT/"
done

# --- per-service virtualenvs --------------------------------------------------
for service_dir in "$RELEASE_ROOT"/services/*/; do
    service_name="$(basename "$service_dir")"
    if [ -f "$service_dir/requirements.txt" ]; then
        echo "creating venv for $service_name"
        run python3 -m venv "$service_dir/.venv"
        run "$service_dir/.venv/bin/pip" install --quiet --upgrade pip
        # Run from inside service_dir, in a subshell so the cd doesn't leak
        # to the rest of the script - each requirements.txt's `-e
        # ../../packages/...` lines are written relative to the service
        # directory (matching every service's own documented local dev
        # workflow: `cd services/X && pip install -r requirements-dev.txt`),
        # not relative to wherever install.sh itself was invoked from. pip
        # resolves editable paths against its own CWD, not the requirements
        # file's location, so without this cd those lines fail to resolve.
        #
        # The second install (-e .) installs the service's OWN package
        # (services/X/pyproject.toml) into its venv - requirements.txt only
        # ever lists its *dependencies* (device_core, strategy_engine, ...),
        # never the service itself. Without this, `python -m X.main` fails
        # with ModuleNotFoundError: No module named 'X' - caught live on
        # real Pi 5 hardware, where every service hit this identically.
        ( cd "$service_dir" && run .venv/bin/pip install --quiet -r requirements.txt && run .venv/bin/pip install --quiet -e . )
    fi
done

# --- vendor the 3.5" LCD driver (offline-available for first boot) -----------
# Cloned here, once, on this networked provisioning host - NOT at Pi
# first-boot time. The LCD is how a customer reads the Wi-Fi onboarding
# instructions (device_agent's wifi_setup screen), so its driver can't wait
# on the Wi-Fi that onboarding itself is establishing. See image/README.md
# "LCD display setup" for the full chicken-and-egg reasoning. Left in place
# across re-installs (not under /opt/monstrapro/releases/$VERSION, which
# gets replaced on every update) - image/scripts/lcd-setup.sh's own marker
# files are what make re-running it a no-op, not this clone step.
LCD_VENDOR_DIR="/opt/monstrapro/vendor/LCD-show"
if [ -d "$LCD_VENDOR_DIR" ]; then
    echo "LCD-show already vendored at $LCD_VENDOR_DIR - skipping clone"
else
    run mkdir -p "$(dirname "$LCD_VENDOR_DIR")"
    run git clone --depth 1 https://github.com/goodtft/LCD-show.git "$LCD_VENDOR_DIR"
fi

# --- activate this release ----------------------------------------------------
run ln -sfn "$RELEASE_ROOT" /opt/monstrapro/current
run chown -R monstrapro:monstrapro /opt/monstrapro/releases /var/lib/monstrapro

# --- config ----------------------------------------------------------------
run cp -n "$REPO_ROOT/image/config/monstrapro.toml" /etc/monstrapro/config.toml

run mkdir -p /etc/NetworkManager/dnsmasq-shared.d
run cp "$REPO_ROOT/image/config/dnsmasq-setup-domain.conf" \
    /etc/NetworkManager/dnsmasq-shared.d/monstra-setup.conf

# --- runtime env (SDL video driver + framebuffer target) ---------------------
# Every monstrapro-*.service loads this via EnvironmentFile=-/etc/monstrapro/env.
# This is what was missing on real Pi 5 hardware bring-up: the file never got
# created at all, so no service ever saw an SDL_VIDEODRIVER override - and this
# panel (goodtft/MHS35) has no /dev/dri, so SDL_VIDEODRIVER=kmsdrm (the
# original plan, previously set by the now-deleted deploy/systemd) could never
# have worked here anyway. display instead renders off-screen and writes
# straight into MONSTRAPRO_FB_DEVICE itself - see
# services/display/src/display/framebuffer.py. `-n`-style guard (matching
# config.toml above): never clobber a device-specific override on a re-install.
if [ ! -f /etc/monstrapro/env ]; then
    run bash -c "cat > /etc/monstrapro/env" <<'ENVEOF'
SDL_VIDEODRIVER=dummy
MONSTRAPRO_FB_DEVICE=/dev/fb0
ENVEOF
fi

# --- stop the console fighting the LCD for the same framebuffer --------------
# image/config/image.toml's intent: "Boots to a text console, no desktop
# environment, no login prompt - display is the only thing on screen." On
# real hardware getty@tty1 (with autologin) was left running and printing
# straight to the same /dev/fb0 the LCD driver maps to - since nothing ever
# took the framebuffer away from it (no KMS/DRM device for a display manager
# or SDL to grab exclusively on this panel), that console/login shell is what
# was actually visible on the LCD, indefinitely. `mask` (not just `disable`)
# because tty1's getty is otherwise started unconditionally regardless of
# enablement. SSH remains the only access path (Instructions.txt) - unrelated
# to this.
run systemctl mask getty@tty1.service
run systemctl stop getty@tty1.service

# --- systemd units -----------------------------------------------------------
run cp "$REPO_ROOT"/image/systemd/monstrapro-*.service "$REPO_ROOT"/image/systemd/monstrapro-*.timer \
    /etc/systemd/system/
run systemctl daemon-reload
run systemctl enable monstrapro-firstboot.service
run systemctl enable monstrapro-lcd-setup.service
run systemctl enable monstrapro-agent.service
run systemctl enable monstrapro-display.service
run systemctl enable monstrapro-worker.service
run systemctl enable monstrapro-portfolio-web.service
run systemctl enable monstrapro-updater.timer

cat <<'EOF'

Install complete. Still needed before services will run cleanly (see
image/README.md "What remains before the first real Raspberry Pi image can
be flashed"):
  - A NetworkManager polkit rule granting the `monstrapro` user permission
    to create/modify Wi-Fi connections (hotspot + join+save) without
    interactive auth.
  - A polkit/sudoers rule letting `monstrapro` run `systemctl restart
    monstrapro-worker.service monstrapro-display.service` (needed by
    services/updater's release-apply flow).
  - Validation of the real Wi-Fi hardware's `nmcli` output against
    device_agent/network.py's NetworkManagerClient parsing.
  - The 3.5in LCD driver (monstrapro-lcd-setup.service) installs on first
    boot and WILL REBOOT THE PI automatically the first time - this is
    expected, not a failure. See image/README.md "LCD display setup".
EOF
