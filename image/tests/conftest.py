from pathlib import Path

import pytest

IMAGE_DIR = Path(__file__).resolve().parent.parent
SYSTEMD_DIR = IMAGE_DIR / "systemd"
SCRIPTS_DIR = IMAGE_DIR / "scripts"


def _parse_unit_file(path: Path) -> dict:
    """Tiny systemd-unit-file parser - good enough for the plain
    key=value units under image/systemd/, not a general INI parser."""
    sections: dict = {}
    current = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is not None and "=" in line:
            key, _, value = line.partition("=")
            sections[current].setdefault(key.strip(), []).append(value.strip())
    return sections


@pytest.fixture
def systemd_dir() -> Path:
    return SYSTEMD_DIR


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def parse_unit_file():
    return _parse_unit_file
