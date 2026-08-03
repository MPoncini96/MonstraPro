import os

import pygame
import pytest

from display.framebuffer import FramebufferWriter


@pytest.fixture(autouse=True)
def _sdl_dummy_driver(monkeypatch):
    # No real display available in CI/dev - same technique pygame_renderer.py's
    # own docstring describes using for headless rendering.
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    yield
    pygame.display.quit()


def _fake_fb_sysfs(tmp_path, *, virtual_size="4,2", bits_per_pixel="16"):
    sys_dir = tmp_path / "sysfs"
    sys_dir.mkdir()
    (sys_dir / "virtual_size").write_text(virtual_size)
    (sys_dir / "bits_per_pixel").write_text(bits_per_pixel)
    return sys_dir


def test_detect_size_reads_virtual_size_from_sysfs(tmp_path):
    sys_dir = _fake_fb_sysfs(tmp_path, virtual_size="480,320")
    writer = FramebufferWriter(str(tmp_path / "fb0"), sys_dir=str(sys_dir))

    assert writer.detect_size() == (480, 320)


def test_open_rejects_a_panel_that_is_not_16bpp(tmp_path):
    """Regression guard: writing RGB565-packed bytes into a differently-shaped
    framebuffer would silently produce garbled output rather than an error -
    this panel is confirmed 16bpp on real Pi 5 hardware (fbset -fb /dev/fb0),
    but a future/different panel reporting otherwise must fail loudly."""
    sys_dir = _fake_fb_sysfs(tmp_path, bits_per_pixel="32")
    device_path = tmp_path / "fb0"
    device_path.write_bytes(b"\x00" * (4 * 2 * 4))
    writer = FramebufferWriter(str(device_path), sys_dir=str(sys_dir))

    with pytest.raises(RuntimeError, match="32bpp"):
        writer.open(4, 2)


def test_write_before_open_raises():
    writer = FramebufferWriter("/dev/fb0")
    surface = pygame.Surface((2, 2))

    with pytest.raises(RuntimeError, match="open"):
        writer.write(surface)


def test_write_packs_pixels_as_little_endian_rgb565(tmp_path):
    width, height = 2, 1
    sys_dir = _fake_fb_sysfs(tmp_path, virtual_size=f"{width},{height}")
    device_path = tmp_path / "fb0"
    # mmap requires the backing file to already be at least as large as the
    # requested mapping - a real /dev/fb0 is always sized this way already.
    device_path.write_bytes(b"\x00" * (width * height * 2))
    writer = FramebufferWriter(str(device_path), sys_dir=str(sys_dir))
    writer.open(width, height)

    surface = pygame.Surface((width, height))
    surface.set_at((0, 0), (255, 0, 0))  # pure red -> 0xF800
    surface.set_at((1, 0), (0, 255, 0))  # pure green -> 0x07E0
    writer.write(surface)
    writer.close()

    raw = device_path.read_bytes()
    assert raw == (0xF800).to_bytes(2, "little") + (0x07E0).to_bytes(2, "little")


def test_close_before_open_is_a_safe_no_op():
    writer = FramebufferWriter("/dev/fb0")
    writer.close()  # must not raise
