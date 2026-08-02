"""Static assertions on image/scripts/lcd-setup.sh content - bash, never
executed by this suite (Linux-only, needs root + real Pi hardware to mean
anything). Reading the file as text is safe anywhere, including Windows."""


def _text(scripts_dir) -> str:
    return (scripts_dir / "lcd-setup.sh").read_text()


def test_refuses_non_linux_and_supports_dry_run(scripts_dir):
    text = _text(scripts_dir)
    assert "uname -s" in text
    assert "--dry-run" in text
    assert "DRY_RUN" in text


def test_requires_root_unless_dry_run(scripts_dir):
    text = _text(scripts_dir)
    assert 'id -u' in text
    assert '"$DRY_RUN" != "1"' in text


def test_rotation_defaults_to_180_and_is_configurable(scripts_dir):
    text = _text(scripts_dir)
    assert 'ROTATION="${MONSTRAPRO_LCD_ROTATION:-180}"' in text
    assert "--rotation" in text


def test_rotation_is_validated_against_known_values(scripts_dir):
    text = _text(scripts_dir)
    assert "VALID_ROTATIONS" in text
    for value in ("0", "90", "180", "270"):
        assert value in text


def test_idempotent_via_marker_files_written_before_the_rebooting_step(scripts_dir):
    text = _text(scripts_dir)
    assert ".lcd-driver-installed" in text
    assert ".lcd-rotation-$ROTATION" in text
    # The marker write must precede the command that might reboot the box,
    # not follow it - otherwise a reboot mid-step means the marker is never
    # written and the step re-runs forever on every future boot.
    # Search for the actual invocations (`run ./...`), not the header
    # comment's earlier description of the historical manual process.
    driver_marker_index = text.index("touch \"$DRIVER_MARKER\"")
    mhs35_index = text.index("run ./MHS35-show")
    assert driver_marker_index < mhs35_index

    rotation_marker_index = text.index("touch \"$ROTATION_MARKER\"")
    rotate_index = text.index("run ./rotate.sh")
    assert rotation_marker_index < rotate_index


def test_skips_reinstall_when_driver_marker_present(scripts_dir):
    text = _text(scripts_dir)
    assert 'if [ -f "$DRIVER_MARKER" ]' in text
    assert "skipping MHS35-show" in text


def test_skips_reapplying_rotation_when_marker_present(scripts_dir):
    text = _text(scripts_dir)
    assert 'if [ -f "$ROTATION_MARKER" ]' in text
    assert "skipping rotate.sh" in text


def test_vendors_lcd_show_only_if_not_already_present(scripts_dir):
    text = _text(scripts_dir)
    assert "goodtft/LCD-show.git" in text
    assert 'if [ -d "$VENDOR_DIR" ]' in text
    assert "git clone" in text


def test_mentions_hdmi_is_not_required_after_setup(scripts_dir):
    text = _text(scripts_dir).lower()
    assert "hdmi" in text
    assert "not required" in text


def test_never_calls_sudo_since_it_already_requires_root(scripts_dir):
    """Invoking `sudo` from inside a systemd service with no controlling
    terminal can hang boot waiting for a password prompt - the script must
    require root itself (see test_requires_root_unless_dry_run) and then
    call the vendor scripts directly. The historical manual process (which
    did use sudo, run interactively by a human) is only ever referenced in
    comments, never in code that actually executes."""
    executable_lines = [
        line for line in _text(scripts_dir).splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert not any("sudo " in line for line in executable_lines)


def test_has_no_obviously_destructive_wildcard_removal(scripts_dir):
    text = _text(scripts_dir)
    assert "rm -rf /" not in text
    assert "rm -rf $" not in text


def test_vendor_path_matches_install_sh(scripts_dir):
    """install.sh vendors LCD-show at provisioning time so a customer
    device never needs internet just to configure its display - both
    scripts must agree on exactly where that ends up."""
    lcd_setup_text = _text(scripts_dir)
    install_text = (scripts_dir / "install.sh").read_text()
    assert "/opt/monstrapro/vendor/LCD-show" in lcd_setup_text
    assert "/opt/monstrapro/vendor/LCD-show" in install_text
