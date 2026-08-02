"""Static assertions on image/systemd/*.service|*.timer content - catches a
future edit silently breaking boot order, the non-root requirement, or the
"display/agent must not wait on full network-online" design decision,
without needing a real systemd to run them against."""

NON_ROOT_SERVICES = [
    "monstrapro-agent.service",
    "monstrapro-display.service",
    "monstrapro-worker.service",
    "monstrapro-portfolio-web.service",
    "monstrapro-updater.service",
]


def test_all_expected_unit_files_exist(systemd_dir):
    expected = {
        "monstrapro-firstboot.service",
        "monstrapro-lcd-setup.service",
        "monstrapro-agent.service",
        "monstrapro-display.service",
        "monstrapro-worker.service",
        "monstrapro-portfolio-web.service",
        "monstrapro-updater.service",
        "monstrapro-updater.timer",
    }
    actual = {p.name for p in systemd_dir.iterdir() if p.suffix in (".service", ".timer")}
    assert actual == expected


def test_normal_services_run_as_dedicated_non_root_user(systemd_dir, parse_unit_file):
    for name in NON_ROOT_SERVICES:
        service = parse_unit_file(systemd_dir / name)["Service"]
        assert service["User"] == ["monstrapro"], f"{name} must run as User=monstrapro"


def test_firstboot_service_has_no_explicit_user_ie_runs_as_root(systemd_dir, parse_unit_file):
    service = parse_unit_file(systemd_dir / "monstrapro-firstboot.service")["Service"]
    assert "User" not in service


def test_firstboot_is_idempotent_and_ordered_before_the_other_services(systemd_dir, parse_unit_file):
    unit = parse_unit_file(systemd_dir / "monstrapro-firstboot.service")
    assert unit["Unit"]["ConditionPathExists"] == ["!/var/lib/monstrapro/.firstboot-complete"]
    before = " ".join(unit["Unit"]["Before"])
    for name in ("monstrapro-agent.service", "monstrapro-worker.service", "monstrapro-display.service"):
        assert name in before


def test_display_starts_without_waiting_on_full_network(systemd_dir, parse_unit_file):
    unit = parse_unit_file(systemd_dir / "monstrapro-display.service")
    after = " ".join(unit["Unit"].get("After", []))
    assert "network-online.target" not in after
    assert "local-fs.target" in after


def test_agent_waits_on_networkmanager_daemon_not_network_online(systemd_dir, parse_unit_file):
    """The agent's whole job is to *establish* connectivity - ordering it
    after network-online.target would deadlock on a genuine first boot with
    no saved Wi-Fi (see image/README.md "Boot order")."""
    unit = parse_unit_file(systemd_dir / "monstrapro-agent.service")
    after = " ".join(unit["Unit"].get("After", []))
    assert "NetworkManager.service" in after
    assert "network-online.target" not in after


def test_agent_grants_only_the_two_capabilities_it_needs(systemd_dir, parse_unit_file):
    service = parse_unit_file(systemd_dir / "monstrapro-agent.service")["Service"]
    caps = set(" ".join(service["AmbientCapabilities"]).split())
    assert caps == {"CAP_NET_ADMIN", "CAP_NET_BIND_SERVICE"}


def test_worker_updater_and_portfolio_web_wait_for_full_network(systemd_dir, parse_unit_file):
    for name in ("monstrapro-worker.service", "monstrapro-updater.service", "monstrapro-portfolio-web.service"):
        unit = parse_unit_file(systemd_dir / name)
        after = " ".join(unit["Unit"].get("After", []))
        assert "network-online.target" in after


def test_exec_start_paths_point_under_opt_monstrapro_current(systemd_dir, parse_unit_file):
    for name, module in [
        ("monstrapro-agent.service", "device_agent.main"),
        ("monstrapro-display.service", "display.main"),
        ("monstrapro-worker.service", "trading_worker.main"),
        ("monstrapro-portfolio-web.service", "portfolio_web.main"),
        ("monstrapro-updater.service", "updater.main"),
    ]:
        exec_start = parse_unit_file(systemd_dir / name)["Service"]["ExecStart"][0]
        assert exec_start.startswith("/opt/monstrapro/current/services/")
        assert exec_start.endswith(f"-m {module}")


def test_portfolio_web_grants_only_port_bind_capability(systemd_dir, parse_unit_file):
    """Unlike monstrapro-agent (which also needs CAP_NET_ADMIN to manage
    Wi-Fi connections), portfolio_web only ever binds a port - it must not
    be granted network-management capabilities it doesn't need."""
    service = parse_unit_file(systemd_dir / "monstrapro-portfolio-web.service")["Service"]
    caps = set(" ".join(service["AmbientCapabilities"]).split())
    assert caps == {"CAP_NET_BIND_SERVICE"}


def test_updater_timer_runs_hourly_after_a_short_boot_delay(systemd_dir, parse_unit_file):
    timer = parse_unit_file(systemd_dir / "monstrapro-updater.timer")["Timer"]
    assert timer["OnBootSec"] == ["5min"]
    assert timer["OnUnitActiveSec"] == ["1h"]


def test_restartable_services_restart_on_failure(systemd_dir, parse_unit_file):
    for name in (
        "monstrapro-agent.service",
        "monstrapro-display.service",
        "monstrapro-worker.service",
        "monstrapro-portfolio-web.service",
    ):
        service = parse_unit_file(systemd_dir / name)["Service"]
        assert service["Restart"] == ["on-failure"]


def test_lcd_setup_runs_as_root_once_before_the_other_services(systemd_dir, parse_unit_file):
    unit = parse_unit_file(systemd_dir / "monstrapro-lcd-setup.service")
    assert "User" not in unit["Service"]  # root, like firstboot - installs a kernel overlay
    assert unit["Service"]["Type"] == ["oneshot"]
    assert unit["Service"]["RemainAfterExit"] == ["yes"]
    assert unit["Service"]["ExecStart"] == ["/opt/monstrapro/current/image/scripts/lcd-setup.sh"]

    before = " ".join(unit["Unit"].get("Before", []))
    for name in ("monstrapro-agent.service", "monstrapro-worker.service", "monstrapro-display.service"):
        assert name in before

    after = " ".join(unit["Unit"].get("After", []))
    assert "monstrapro-firstboot.service" in after
    assert "network-online.target" not in after  # must not wait on the Wi-Fi onboarding shows on this LCD


def test_lcd_setup_is_ordered_but_not_required_by_the_other_services(systemd_dir, parse_unit_file):
    """LCD-setup failing shouldn't block trading/agent/display from starting
    - it's a display-config nicety, not a correctness requirement, unlike
    monstrapro-firstboot.service's Requisite= (which IS required)."""
    for name in ("monstrapro-agent.service", "monstrapro-display.service", "monstrapro-worker.service"):
        unit = parse_unit_file(systemd_dir / name)
        after = " ".join(unit["Unit"].get("After", []))
        assert "monstrapro-lcd-setup.service" in after
        requisite = " ".join(unit["Unit"].get("Requisite", []))
        assert "monstrapro-lcd-setup.service" not in requisite
