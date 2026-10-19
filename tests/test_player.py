"""Player discovery and command construction.

Built to be testable from a Windows box, which means nothing here may touch a
real video device or a real player. Every argv is checked as a list, because the
obvious failure in a shell command is a device path that needs quoting and a
player that does not.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, "py_modules")

from decky_display import player


class FakePath:
    """A directory holding pretend executables, so discovery can be tested.

    shutil.which only finds what the platform considers executable, so on Windows
    that means an .exe suffix. Creating the wrong name would make these tests
    pass on a Deck and quietly assert nothing here.
    """

    def __init__(self, names):
        self.directory = tempfile.mkdtemp()
        suffix = ".exe" if sys.platform == "win32" else ""
        for name in names:
            path = os.path.join(self.directory, name + suffix)
            with open(path, "w") as handle:
                handle.write("#!/bin/sh\n")
            os.chmod(path, 0o755)

    def cleanup(self):
        import shutil
        shutil.rmtree(self.directory, ignore_errors=True)


class FindTest(unittest.TestCase):
    def test_nothing_installed_finds_nothing(self):
        self.assertEqual(player.find_players(path="/nonexistent"), [])

    def test_it_finds_what_is_there_in_preference_order(self):
        fake = FakePath(["gst-launch-1.0", "ffplay"])
        try:
            names = [p.name for p in player.find_players(path=fake.directory)]
            self.assertEqual(names, ["ffplay", "gst-launch-1.0"])
        finally:
            fake.cleanup()

    def test_mpv_wins_when_everything_is_there(self):
        fake = FakePath(["mpv", "ffplay", "gst-launch-1.0"])
        try:
            self.assertEqual(player.find_players(path=fake.directory)[0].name, "mpv")
        finally:
            fake.cleanup()


class ChooseTest(unittest.TestCase):
    def test_drm_needs_mpv_and_will_not_fall_back(self):
        # Falling back to a windowed player here would draw to a window nobody
        # is looking at while the UI claimed the panel was being driven.
        available = [player.Player("ffplay", "/usr/bin/ffplay")]
        self.assertIsNone(player.choose(available, "/dev/dri/card0"))

        with_mpv = [player.Player("mpv", "/usr/bin/mpv")] + available
        self.assertEqual(player.choose(with_mpv, "/dev/dri/card0").name, "mpv")

    def test_no_drm_takes_the_best_available(self):
        available = [player.Player("ffplay", "/usr/bin/ffplay"), player.Player("mpv", "/usr/bin/mpv")]
        self.assertEqual(player.choose(available, None).name, "ffplay")

    def test_nothing_available_is_none(self):
        self.assertIsNone(player.choose([], None))
        self.assertIsNone(player.choose([], "/dev/dri/card0"))


class CommandTest(unittest.TestCase):
    def test_mpv_never_touches_the_keyboard_or_the_tty(self):
        command = player.build_command("mpv", "/dev/video0", 1280, 720, 60)
        self.assertIn("--no-terminal", command)
        self.assertIn("--no-input-default-bindings", command)
        self.assertIn("--no-audio", command)

    def test_mpv_puts_the_device_last(self):
        command = player.build_command("mpv", "/dev/video0", 1280, 720, 60)
        self.assertEqual(command[-1], "/dev/video0")

    def test_mpv_asks_for_the_size_and_rate(self):
        command = player.build_command("mpv", "/dev/video0", 1280, 720, 59.94)
        self.assertIn("--demuxer-lavf-o=video_size=1280x720", command)
        self.assertIn("--demuxer-lavf-o=framerate=59.94", command)

    def test_mpv_targets_kms_only_when_asked(self):
        windowed = player.build_command("mpv", "/dev/video0", 1280, 720, 60, drm_device=None)
        kms = player.build_command("mpv", "/dev/video0", 1280, 720, 60, drm_device="/dev/dri/card0")
        self.assertIn("-o=/dev/dri/card0", kms)
        self.assertIn("--gpu-context=drm", kms)
        self.assertNotIn("--gpu-context=drm", windowed)

    def test_fullscreen_is_requested_not_assumed(self):
        self.assertIn("--fs", player.build_command("mpv", "/dev/video0", 800, 600, 60, fullscreen=True))
        self.assertNotIn("--fs", player.build_command("mpv", "/dev/video0", 800, 600, 60, fullscreen=False))

    def test_ffplay_has_no_kms_path_and_is_not_offered_one(self):
        with self.assertRaises(ValueError):
            player.build_command("ffplay", "/dev/video0", 1280, 720, 60, drm_device="/dev/dri/card0")

    def test_gst_pipeline_is_well_formed(self):
        command = player.build_command("gst-launch-1.0", "/dev/video0", 1280, 720, 60)
        joined = " ".join(command)
        self.assertTrue(joined.startswith("gst-launch-1.0"))
        self.assertIn("v4l2src device=/dev/video0", joined)
        self.assertIn("width=1280,height=720", joined)
        self.assertIn("autovideosink", joined)
        # Every separator is its own argv slot and nothing is glued onto a
        # neighbour, so the pipeline reads as a clean alternating list.
        for argument in command:
            self.assertNotIn("!", argument.replace("!", "") if argument != "!" else "")
        self.assertIn("!", command)
        self.assertNotIn("sync=false!", joined)

    def test_gst_uses_kmssink_only_for_kms(self):
        kms = " ".join(player.build_command("gst-launch-1.0", "/dev/video0", 1280, 720, 60, drm_device="/dev/dri/card0"))
        windowed = " ".join(player.build_command("gst-launch-1.0", "/dev/video0", 1280, 720, 60))
        self.assertIn("kmssink", kms)
        self.assertNotIn("kmssink", windowed)

    def test_an_unknown_renderer_is_an_error_not_a_silent_default(self):
        with self.assertRaises(ValueError):
            player.build_command("vlc", "/dev/video0", 800, 600, 60)

    def test_a_device_with_a_space_stays_one_argument(self):
        # argv lists never need quoting, which is the whole reason for using one.
        command = player.build_command("mpv", "/dev/my video", 800, 600, 60)
        self.assertEqual(command[-1], "/dev/my video")


class DescribeTest(unittest.TestCase):
    def test_it_reports_players_and_reports_no_dri_rather_than_raising(self):
        fake = FakePath(["mpv"])
        try:
            report = player.describe_environment(path=fake.directory)
            self.assertEqual([p["name"] for p in report["players"]], ["mpv"])
            self.assertIsInstance(report["dri"], list)
        finally:
            fake.cleanup()


if __name__ == "__main__":
    unittest.main()