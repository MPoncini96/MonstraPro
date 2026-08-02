import tarfile
from pathlib import Path

import pytest

from updater import release_store
from updater.release_store import ReleaseStoreError


def _make_archive(tmp_path, name="release.tar.gz", *, files: dict[str, str] | None = None) -> Path:
    files = files or {"VERSION": "1.1.0"}
    archive_path = tmp_path / name
    with tarfile.open(archive_path, "w:gz") as tar:
        for filename, content in files.items():
            src = tmp_path / f"_src_{filename.replace('/', '_')}"
            src.write_text(content)
            tar.add(src, arcname=filename)
    return archive_path


class TestParseVersion:
    def test_parses_dotted_integers(self):
        assert release_store.parse_version("1.2.3") == (1, 2, 3)

    def test_rejects_non_numeric_components(self):
        with pytest.raises(ReleaseStoreError):
            release_store.parse_version("1.2.rc1")


class TestIsNewer:
    def test_anything_is_newer_than_none(self):
        assert release_store.is_newer("1.0.0", None) is True

    def test_higher_version_is_newer(self):
        assert release_store.is_newer("1.1.0", "1.0.0") is True

    def test_equal_version_is_not_newer(self):
        assert release_store.is_newer("1.0.0", "1.0.0") is False

    def test_lower_version_is_not_newer(self):
        assert release_store.is_newer("1.0.0", "1.1.0") is False


class TestExtractRelease:
    def test_extracts_archive_contents(self, tmp_path):
        archive = _make_archive(tmp_path, files={"VERSION": "1.1.0", "bin/run.sh": "#!/bin/sh"})
        releases_dir = tmp_path / "releases"

        target = release_store.extract_release(archive, releases_dir, "1.1.0")

        assert target == releases_dir / "1.1.0"
        assert (target / "VERSION").read_text() == "1.1.0"
        assert (target / "bin" / "run.sh").exists()

    def test_refuses_to_overwrite_existing_version(self, tmp_path):
        archive = _make_archive(tmp_path)
        releases_dir = tmp_path / "releases"
        release_store.extract_release(archive, releases_dir, "1.1.0")

        with pytest.raises(ReleaseStoreError):
            release_store.extract_release(archive, releases_dir, "1.1.0")

    def test_rejects_path_traversal_in_archive(self, tmp_path):
        archive_path = tmp_path / "evil.tar.gz"
        evil_src = tmp_path / "evil_file"
        evil_src.write_text("gotcha")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(evil_src, arcname="../../evil")

        releases_dir = tmp_path / "releases"
        with pytest.raises(Exception):  # tarfile's "data" filter raises for traversal attempts
            release_store.extract_release(archive_path, releases_dir, "1.1.0")

        assert not (releases_dir / "1.1.0").exists()
        # the staging directory must not be left behind on failure either
        assert not (releases_dir / ".1.1.0.staging").exists()


class TestPruneOldReleases:
    def test_keeps_only_the_n_highest_versions(self, tmp_path):
        releases_dir = tmp_path / "releases"
        for version in ["1.0.0", "1.1.0", "1.2.0", "1.3.0", "1.4.0"]:
            (releases_dir / version).mkdir(parents=True)

        deleted = release_store.prune_old_releases(releases_dir, keep=3)

        assert set(deleted) == {"1.0.0", "1.1.0"}
        remaining = {p.name for p in releases_dir.iterdir()}
        assert remaining == {"1.2.0", "1.3.0", "1.4.0"}

    def test_missing_releases_dir_returns_empty(self, tmp_path):
        assert release_store.prune_old_releases(tmp_path / "nonexistent", keep=3) == []


class TestSwapCurrentSymlink:
    def test_swap_and_read_back_current_version(self, tmp_path):
        releases_dir = tmp_path / "releases"
        (releases_dir / "1.0.0").mkdir(parents=True)

        try:
            release_store.swap_current_symlink(tmp_path, "1.0.0")
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        assert release_store.current_version(tmp_path) == "1.0.0"

    def test_swap_updates_existing_symlink(self, tmp_path):
        releases_dir = tmp_path / "releases"
        (releases_dir / "1.0.0").mkdir(parents=True)
        (releases_dir / "1.1.0").mkdir(parents=True)

        try:
            release_store.swap_current_symlink(tmp_path, "1.0.0")
            release_store.swap_current_symlink(tmp_path, "1.1.0")
        except OSError:
            pytest.skip("symlink creation not permitted in this environment")

        assert release_store.current_version(tmp_path) == "1.1.0"

    def test_refuses_to_point_at_unextracted_version(self, tmp_path):
        with pytest.raises(ReleaseStoreError):
            release_store.swap_current_symlink(tmp_path, "9.9.9")

    def test_current_version_none_when_no_symlink(self, tmp_path):
        assert release_store.current_version(tmp_path) is None
