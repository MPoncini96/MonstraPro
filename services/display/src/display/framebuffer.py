"""Direct /dev/fb0 writer for SPI framebuffer-only panels (goodtft/MHS35 and
similar) that have no KMS/DRM device at all - confirmed on real Pi 5
hardware: `ls /dev/dri` comes back empty, only `/dev/fb0` exists. SDL2 has no
driver that can draw straight into a bare fbdev on this hardware (kmsdrm
needs /dev/dri, which this panel never has, and no X/Wayland compositor
runs here) - every SDL video driver on the device probes to "not available"
except the invisible `dummy`/`offscreen` ones. See pygame_renderer.py's
module docstring for how this is wired in: pygame renders normally with
SDL_VIDEODRIVER=dummy, and this module blits the finished surface into the
real framebuffer by hand each frame.

Only 16bpp RGB565 is supported - that's what this panel reports via
/sys/class/graphics/fb0/bits_per_pixel, matching goodtft/LCD-show's MHS35
driver. A panel reporting anything else fails loudly rather than writing
garbled pixels.
"""

from __future__ import annotations

import mmap
import os

import numpy as np
import pygame


class FramebufferWriter:
    def __init__(self, device: str = "/dev/fb0", *, sys_dir: str | None = None) -> None:
        # sys_dir is only ever overridden by tests, which can't write to the
        # real /sys/class/graphics/fb0 - production callers always use the
        # device-derived default.
        self._device = device
        self._sys_dir = sys_dir or f"/sys/class/graphics/{os.path.basename(device)}"
        self._fd: int | None = None
        self._mmap: mmap.mmap | None = None

    def detect_size(self) -> tuple[int, int]:
        width, height = (int(part) for part in self._read_sys("virtual_size").split(","))
        return width, height

    def open(self, width: int, height: int) -> None:
        bpp = int(self._read_sys("bits_per_pixel"))
        if bpp != 16:
            raise RuntimeError(f"{self._device} reports {bpp}bpp - only 16bpp (RGB565) is supported")
        size_bytes = width * height * 2
        self._fd = os.open(self._device, os.O_RDWR)
        # access=ACCESS_WRITE (rather than the Unix-only flags=/prot=
        # combination) is the one mmap() form that works both on the real
        # device (Linux) and on this project's Windows dev machines, where
        # mmap.MAP_SHARED/PROT_WRITE don't exist at all - see
        # image/README.md "Local development / simulation (Windows-safe)".
        self._mmap = mmap.mmap(self._fd, size_bytes, access=mmap.ACCESS_WRITE)

    def write(self, surface: pygame.Surface) -> None:
        if self._mmap is None:
            raise RuntimeError("FramebufferWriter.open() must be called before write()")
        # array3d is (width, height, 3); the framebuffer is scanline-major
        # (height, width), same transpose pygame's own docs use for fbdev-style output.
        rgb = pygame.surfarray.array3d(surface).transpose(1, 0, 2).astype(np.uint16)
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        # RGB565: confirmed via `fbset -fb /dev/fb0` -> rgba 5/11,6/5,5/0,0/0
        # (5-bit red at bit 11, 6-bit green at bit 5, 5-bit blue at bit 0).
        pixels565 = (((r >> 3) & 0x1F) << 11) | (((g >> 2) & 0x3F) << 5) | ((b >> 3) & 0x1F)
        self._mmap.seek(0)
        self._mmap.write(pixels565.astype("<u2").tobytes())

    def close(self) -> None:
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _read_sys(self, name: str) -> str:
        with open(f"{self._sys_dir}/{name}") as f:
            return f.read().strip()
