from updater.manifest_client import NullManifestClient, ReleaseManifest


def test_null_client_always_reports_no_manifest():
    assert NullManifestClient().fetch() is None


def test_release_manifest_defaults_are_empty_not_none():
    manifest = ReleaseManifest(version="1.0.0")
    assert manifest.strategy_updates == {}
    assert manifest.notifications == []
    assert manifest.artifact_url is None
    assert manifest.artifact_signature is None
