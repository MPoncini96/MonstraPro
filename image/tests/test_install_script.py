"""Static assertions on image/scripts/*.sh content - these scripts are bash
and are never executed by this suite (this project's own rule: never run
NetworkManager/access-point/disk-image/destructive commands on Windows, and
more generally these need root + a real systemd host to mean anything).
Reading the file as text is safe anywhere."""


def _text(scripts_dir, name: str) -> str:
    return (scripts_dir / name).read_text()


def test_install_script_refuses_non_linux_and_supports_dry_run(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    assert 'uname -s' in text
    assert "--dry-run" in text
    assert "DRY_RUN" in text


def test_install_script_creates_dedicated_non_root_user(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    assert "useradd" in text
    assert "monstrapro" in text
    assert "/usr/sbin/nologin" in text


def test_install_script_creates_opt_and_var_lib_and_etc_layout(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    assert "/opt/monstrapro" in text
    assert "/var/lib/monstrapro" in text
    assert "/etc/monstrapro" in text


def test_install_script_never_clobbers_an_existing_device_config(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    assert "cp -n" in text  # --no-clobber: a re-run must not overwrite a live device's config.toml


def test_install_script_installs_and_enables_all_services_plus_timer(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    for unit in (
        "monstrapro-firstboot.service",
        "monstrapro-lcd-setup.service",
        "monstrapro-agent.service",
        "monstrapro-display.service",
        "monstrapro-worker.service",
        "monstrapro-portfolio-web.service",
        "monstrapro-updater.timer",
    ):
        assert f"systemctl enable {unit}" in text


def test_install_script_vendors_lcd_show_only_if_not_already_present(scripts_dir):
    """LCD driver setup must not need internet access at customer first-boot
    time - it's vendored once here, at provisioning time, on a networked
    host. See image/README.md "LCD display setup"."""
    text = _text(scripts_dir, "install.sh")
    assert "goodtft/LCD-show.git" in text
    assert "/opt/monstrapro/vendor/LCD-show" in text
    assert 'if [ -d "$LCD_VENDOR_DIR" ]' in text


def test_install_script_installs_the_service_package_itself_not_just_its_deps(scripts_dir):
    """Regression guard for a real bug found on physical Pi 5 hardware:
    each service's requirements.txt only lists its *dependencies*
    (device_core, strategy_engine, ...), never the service's own package.
    Without a separate `pip install -e .` from inside the service
    directory, `python -m X.main` fails with
    ModuleNotFoundError: No module named 'X' - hit identically by every
    one of the five services the first time this was run for real."""
    text = _text(scripts_dir, "install.sh")
    assert "pip install --quiet -r requirements.txt" in text
    assert "pip install --quiet -e ." in text


def test_install_script_has_no_obviously_destructive_wildcard_removal(scripts_dir):
    text = _text(scripts_dir, "install.sh")
    assert "rm -rf /" not in text
    assert "rm -rf $" not in text


def test_first_boot_script_is_idempotent_via_marker_file(scripts_dir):
    text = _text(scripts_dir, "first-boot.sh")
    assert ".firstboot-complete" in text
    assert "exit 0" in text


def test_first_boot_script_stays_out_of_networking_entirely(scripts_dir):
    """Design decision: first-boot.sh only fixes directory ownership: the
    Wi-Fi onboarding decision belongs entirely to device_agent (Python,
    testable, injectable) - see image/README.md "First-boot state flow"."""
    text = _text(scripts_dir, "first-boot.sh").lower()
    for forbidden in ("nmcli", "networkmanager", "wifi", "hotspot"):
        assert forbidden not in text
