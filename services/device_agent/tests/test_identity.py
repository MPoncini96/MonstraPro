from device_agent.identity import AP_SSID_PREFIX, ap_ssid_for, ap_suffix_for


def test_ap_ssid_uses_prefix_and_four_char_suffix():
    ssid = ap_ssid_for("MPB-AB12CD34EF56")

    assert ssid.startswith(AP_SSID_PREFIX)
    assert len(ssid) == len(AP_SSID_PREFIX) + 4


def test_ap_ssid_is_deterministic_for_same_serial():
    assert ap_ssid_for("MPB-AB12CD34EF56") == ap_ssid_for("MPB-AB12CD34EF56")


def test_ap_ssid_differs_for_different_serials():
    assert ap_ssid_for("MPB-AAAAAAAAAAAA") != ap_ssid_for("MPB-BBBBBBBBBBBB")


def test_ap_suffix_does_not_contain_the_raw_serial():
    serial = "MPB-AB12CD34EF56"
    suffix = ap_suffix_for(serial)

    assert serial not in suffix
    assert suffix.isupper()
