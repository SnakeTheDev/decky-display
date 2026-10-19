"""V4L2 ioctls, just enough to find a capture device and ask what it can do.

Linux's ``videodev2.h`` in ctypes rather than a compiled helper, because the only
thing needed here is a handful of query ioctls that return fixed-size structs.
Doing it in Python keeps the plugin free of a native build step, which matters for
something a user installs from a zip.

Every struct and ioctl number here is asserted against the values in the kernel
headers by ``tests/test_v4l2.py``. Struct layout is the whole risk in this module:
a field in the wrong place does not raise, it returns plausible nonsense, and on
some kernels a wrong struct size produces an ioctl number that simply fails.
"""

import ctypes
import os

# fcntl is imported where it is used, not here. It only exists on Linux, and
# importing it at module scope makes this file unimportable anywhere else, which
# in turn makes the struct layouts and the mode selection below untestable off
# the Deck.

# Directions, as _IOC() encodes them on x86 and arm. Not the generic _IOC_READ
#/_IOC_WRITE: those are the same two bits on every 64-bit Linux arch, and the Deck
# is x86_64, so the direction can be spelled out.
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, letter: str, number: int, size: int) -> int:
    return (direction << _IOC_DIRSHIFT) | (ord(letter) << _IOC_TYPESHIFT) | (size << _IOC_SIZESHIFT) | (number << _IOC_NRSHIFT)


class Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_uint32 * 16),
        ("card", ctypes.c_uint32 * 32),
        ("bus_info", ctypes.c_uint32 * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class FormatDescription(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_uint8 * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_width", ctypes.c_uint32),
        ("mbus_height", ctypes.c_uint32),
        ("mbus_stride", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 8),
    ]


class FrameSizeEnum(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("discrete", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class FrameIntervalEnum(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("numerator", ctypes.c_uint32),
        ("denominator", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 8),
    ]


# Device types: a capture device, an output device, or both. Anything the Deck can
# show has to be a capture device; /dev/video0 on a machine with a camera is
# usually that too, so the type is checked rather than assumed.
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_OUTPUT = 0x00000002
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000

V4L2_FMT_TYPE_VIDEO_CAPTURE = 1
V4L2_FRMIVAL_TYPE_DISCRETE = 1

# Pixel formats worth accepting, best first. YUYV is the one every USB capture
# adapter and every UVC camera can do, and it needs no conversion. MJPEG is worth
# having because a 1080p60 adapter that offers it is handing us a fraction of the
# USB bandwidth. Anything else is left alone rather than half supported.
PREFERRED_FORMATS = ("MJPG", "YUYV", "NV12")
FORMAT_NAMES = {"MJPG": "Motion JPEG", "YUYV": "YUV 4:2:2 packed", "NV12": "YUV 4:2:0 planar"}


class DeviceError(Exception):
    """A device could not be queried, or answered something nonsensical."""


def _text(raw) -> str:
    """The kernel returns these as a fixed array of uint32 with a NUL in it."""
    raw = bytes(raw)
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _ioctl(fd: int, number: int, argument) -> None:
    import fcntl
    fcntl.ioctl(fd, number, argument)


def query_capability(fd: int) -> Capability:
    capability = Capability()
    _ioctl(fd, _ioc(_IOC_READ, "V", 0, ctypes.sizeof(Capability)), capability)
    return capability


def enumerate_formats(fd: int) -> list:
    formats = []
    for index in range(16):
        description = FormatDescription()
        description.index = index
        description.type = V4L2_FMT_TYPE_VIDEO_CAPTURE
        try:
            _ioctl(fd, _ioc(_IOC_READ, "V", 2, ctypes.sizeof(FormatDescription)), description)
        except OSError:
            break  # index past the end, which is how enumeration ends
        code = description.pixelformat
        name = bytes([(code >> shift) & 0xFF for shift in (0, 8, 16, 24)]).decode("ascii", "replace")
        if name in PREFERRED_FORMATS:
            formats.append(name)
    return formats


def enumerate_sizes(fd: int, pixel_format: int) -> list:
    sizes = []
    for index in range(0, 256):
        entry = FrameSizeEnum()
        entry.index = index
        entry.type = 3  # V4L2_FRMSIZE_TYPE_DISCRETE
        entry.pixel_format = pixel_format
        try:
            _ioctl(fd, _ioc(_IOC_READ, "V", 3, ctypes.sizeof(FrameSizeEnum)), entry)
        except OSError:
            break
        if entry.width and entry.height:
            sizes.append((entry.width, entry.height))
    return sizes


def enumerate_intervals(fd: int, pixel_format: int, width: int, height: int) -> list:
    intervals = []
    for index in range(0, 64):
        entry = FrameIntervalEnum()
        entry.index = index
        entry.pixel_format = pixel_format
        entry.type = V4L2_FRMIVAL_TYPE_DISCRETE
        try:
            _ioctl(fd, _ioc(_IOC_READ, "V", 4, ctypes.sizeof(FrameIntervalEnum)), entry)
        except OSError:
            break
        if entry.numerator and entry.denominator:
            intervals.append(entry.denominator / entry.numerator)
    return intervals


def pixel_format_code(name: str) -> int:
    code = name.encode("ascii")
    return int.from_bytes(code.ljust(4, b"\0")[:4], "little")


class Device:
    """One /dev/video node, and what it can put on the wire."""

    def __init__(self, path: str):
        self.path = path
        self.driver = ""
        self.card = ""
        self.capabilities = 0
        self.modes = []  # list of (width, height, fps, format)

    @property
    def can_capture(self) -> bool:
        caps = self.capabilities
        if caps & V4L2_CAP_DEVICE_CAPS:
            caps = self._device_caps
        return bool(caps & V4L2_CAP_VIDEO_CAPTURE)

    @property
    def _device_caps(self) -> int:
        return getattr(self, "device_caps_value", 0)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "driver": self.driver,
            "card": self.card,
            "can_capture": self.can_capture,
            "modes": [{"width": w, "height": h, "fps": round(fps, 2), "format": fmt}
                      for w, h, fps, fmt in self.modes],
        }


def _query(fd: int, device: Device) -> None:
    capability = query_capability(fd)
    device.driver = _text(capability.driver)
    device.card = _text(capability.card)
    device.capabilities = capability.capabilities
    device.device_caps_value = capability.device_caps

    if not device.can_capture:
        return
    if not (capability.capabilities & V4L2_CAP_STREAMING) and not (
            (capability.capabilities & V4L2_CAP_DEVICE_CAPS) == 0 and capability.device_caps & V4L2_CAP_STREAMING):
        return

    for name in enumerate_formats(fd):
        code = pixel_format_code(name)
        for width, height in enumerate_sizes(fd, code):
            for fps in enumerate_intervals(fd, code, width, height):
                device.modes.append((width, height, fps, name))


def scan(root: str = "/dev") -> list:
    """Every capture device under ``root`` that can actually produce frames."""
    devices = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return devices

    for name in names:
        if not name.startswith("video"):
            continue
        path = os.path.join(root, name)
        device = Device(path)
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue  # in use by a camera app, or permissions
        try:
            _query(fd, device)
        except OSError:
            continue
        finally:
            os.close(fd)
        if device.can_capture and device.modes:
            devices.append(device)
    return devices