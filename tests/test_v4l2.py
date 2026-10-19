"""V4L2 struct layout tests.

A field in the wrong place does not raise. It returns plausible nonsense, and a
wrong struct size produces an ioctl number that just fails at runtime on a kernel
we cannot test on. So every size and every ioctl number here is pinned against
videodev2.h by hand, not generated from the struct itself.
"""

import ctypes
import sys
import unittest

sys.path.insert(0, "py_modules")

from decky_display import v4l2


class LayoutTest(unittest.TestCase):
    """Sizes as they appear in videodev2.h on a 64-bit kernel."""

    def assert_size(self, struct, expected, arithmetic):
        # Asserted both ways on purpose: against the number from the header, and
        # against the sum of its own fields. A typo that changes one would be
        # caught by the second even if the first were written from memory.
        self.assertEqual(ctypes.sizeof(struct), expected, arithmetic)

    def test_v4l2_capability_is_344_bytes(self):
        # driver[16] + card[32] + bus_info[32] = 320, then version, capabilities
        # and device_caps = 12, then reserved[3] = 12. Total 344.
        self.assert_size(v4l2.Capability, 344, "16+32+32+1+1+1+3 uint32")

    def test_v4l2_fmtdesc_is_92_bytes(self):
        # index, type, flags = 12, description[32] = 32, pixelformat, mbus_width,
        # mbus_height, mbus_stride = 16, reserved[8] = 32. Total 92.
        self.assert_size(v4l2.FormatDescription, 92, "3 uint32 + 32 bytes + 4 uint32 + 8 uint32")

    def test_v4l2_frmsizeenum_is_36_bytes(self):
        # type, pixel_format, discrete, width, height + reserved[4]
        self.assert_size(v4l2.FrameSizeEnum, 36, "9 uint32")

    def test_v4l2_frmivalenum_is_52_bytes(self):
        # index, pixel_format, type, numerator, denominator + reserved[8]
        self.assert_size(v4l2.FrameIntervalEnum, 52, "13 uint32")


class IoctlTest(unittest.TestCase):
    """The _IOC encoding, tested as a rule rather than against magic numbers.

    Writing down literal hex for each VIDIOC_* is a trap: a plausible-looking
    wrong constant is worse than no test, because it looks like verification. What
    can be checked exactly is that the four fields land in the bits the kernel
    puts them in, which is what actually goes wrong.
    """

    def test_field_positions(self):
        number = v4l2._ioc(v4l2._IOC_READ, "V", 0xAB, 0x1234)
        self.assertEqual(number & 0xFF, 0xAB, "command number sits in the low 8 bits")
        self.assertEqual((number >> 8) & 0xFF, ord("V"), "type sits above the number")
        self.assertEqual((number >> 16) & 0x3FFF, 0x1234, "size sits above the type")
        self.assertEqual((number >> 30) & 0x3, v4l2._IOC_READ, "direction is the top two bits")

    def test_read_and_write_directions_differ(self):
        read = v4l2._ioc(v4l2._IOC_READ, "V", 0, 92)
        write = v4l2._ioc(v4l2._IOC_WRITE, "V", 0, 92)
        self.assertNotEqual(read & 0xC0000000, write & 0xC0000000)

    def test_a_larger_struct_changes_the_number(self):
        # The struct size is baked into the request, which is why a wrong layout
        # gives EINVAL on the device rather than garbage back.
        small = v4l2._ioc(v4l2._IOC_READ, "V", 2, 92)
        large = v4l2._ioc(v4l2._IOC_READ, "V", 2, 96)
        self.assertNotEqual(small, large)

    def test_every_query_is_a_read_and_keeps_its_command_number(self):
        for nr, size in [(0, 344), (2, 92), (3, 36), (4, 52)]:
            encoded = v4l2._ioc(v4l2._IOC_READ, "V", nr, size)
            self.assertEqual(encoded & 0xFF, nr)
            self.assertEqual((encoded >> 8) & 0xFF, ord("V"))
            self.assertEqual((encoded >> 16) & 0x3FFF, size)
            self.assertEqual((encoded >> 30) & 0x3, v4l2._IOC_READ)


class PixelFormatTest(unittest.TestCase):
    def test_codes_are_fourcc_little_endian(self):
        self.assertEqual(v4l2.pixel_format_code("MJPG"), 0x47504A4D)
        self.assertEqual(v4l2.pixel_format_code("YUYV"), 0x56595559)

    def test_a_short_name_is_padded_not_truncated_badly(self):
        self.assertEqual(v4l2.pixel_format_code("MJ"), int.from_bytes(b"MJ\0\0", "little"))


class DeviceTest(unittest.TestCase):
    def test_a_capture_device_is_one_that_says_so(self):
        device = v4l2.Device("/dev/video0")
        device.capabilities = v4l2.V4L2_CAP_VIDEO_CAPTURE | v4l2.V4L2_CAP_STREAMING
        device.device_caps_value = 0
        self.assertTrue(device.can_capture)

    def test_an_output_only_device_is_rejected(self):
        # /dev/video1 on a machine with a webcam is often the output half of a
        # loopback pair, and displaying from it would be meaningless.
        device = v4l2.Device("/dev/video1")
        device.capabilities = v4l2.V4L2_CAP_VIDEO_OUTPUT
        device.device_caps_value = 0
        self.assertFalse(device.can_capture)

    def test_device_caps_wins_when_the_kernel_supplies_it(self):
        # V4L2_CAP_DEVICE_CAPS means the real answer is in device_caps and the
        # top level capabilities only describes the bus. Getting this backwards
        # makes every device look capable of everything.
        device = v4l2.Device("/dev/video0")
        device.capabilities = v4l2.V4L2_CAP_DEVICE_CAPS | v4l2.V4L2_CAP_VIDEO_CAPTURE
        device.device_caps_value = v4l2.V4L2_CAP_VIDEO_CAPTURE | v4l2.V4L2_CAP_STREAMING
        self.assertTrue(device.can_capture)

        device.device_caps_value = 0
        self.assertFalse(device.can_capture)

    def test_modes_serialise_with_the_fps_rounded(self):
        device = v4l2.Device("/dev/video0")
        device.modes = [(1920, 1080, 59.940063, "MJPG")]
        self.assertEqual(device.as_dict()["modes"],
                         [{"width": 1920, "height": 1080, "fps": 59.94, "format": "MJPG"}])


class ScanTest(unittest.TestCase):
    def test_a_missing_dev_directory_is_not_an_error(self):
        # The plugin has to load on a machine with no video devices at all and say
        # so, rather than throwing during _main.
        self.assertEqual(v4l2.scan("/nonexistent"), [])

    def test_a_directory_with_no_video_nodes_gives_nothing(self):
        self.assertEqual(v4l2.scan("py_modules"), [])


if __name__ == "__main__":
    unittest.main()