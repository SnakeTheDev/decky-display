"""Tests for process handling.

The parts worth testing without a Deck are the failure paths: what the user is
told when there is no player, when the player dies, and when start is pressed
twice. Those are the cases that turn into a dead switch in the UI.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, "py_modules")

from decky_display import player, runner


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    async def wait(self):
        return self.returncode if self.returncode is not None else 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def fake_players(monkey_names):
    return [player.Player(name, f"/usr/bin/{name}") for name in monkey_names]


class DrmTest(unittest.TestCase):
    def test_no_dri_directory_gives_no_cards(self):
        # Must not raise on a machine with no /dev/dri, so the UI can load.
        self.assertEqual(runner.drm_cards(), [])


class StartTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_player_installed_says_so_clearly(self):
        subject = runner.Runner()
        # An empty player list, whichever machine this runs on.
        original = player.find_players
        player.find_players = lambda *a, **k: []
        try:
            with self.assertRaises(RuntimeError) as caught:
                await subject.start("/dev/video0", 1280, 720, 60, None)
            self.assertIn("mpv", str(caught.exception))
        finally:
            player.find_players = original

    async def test_asking_for_kms_without_mpv_is_refused_not_faked(self):
        subject = runner.Runner()
        original = player.find_players
        player.find_players = lambda *a, **k: fake_players(["ffplay"])
        try:
            with self.assertRaises(RuntimeError) as caught:
                await subject.start("/dev/video0", 1280, 720, 60, "/dev/dri/card0")
            self.assertIn("mpv", str(caught.exception))
        finally:
            player.find_players = original

    async def test_starting_twice_replaces_rather_than_leaking_a_player(self):
        subject = runner.Runner()
        original = player.find_players
        player.find_players = lambda *a, **k: fake_players(["mpv"])
        started = []

        async def fake_exec(*command, **kwargs):
            started.append(command)
            process = FakeProcess()
            return process

        original_exec = asyncio.create_subprocess_exec
        asyncio.create_subprocess_exec = fake_exec
        try:
            first = await subject.start("/dev/video0", 1280, 720, 60, None)
            second = await subject.start("/dev/video0", 1280, 720, 60, None)
            self.assertIsNot(first, second)
            self.assertEqual(len(started), 2)
        finally:
            asyncio.create_subprocess_exec = original_exec
            player.find_players = original

    async def test_a_player_that_dies_is_reported_as_an_error(self):
        # The common failure is asking for a mode the adapter will not give.
        # Silent success here looks to the user like a black screen.
        subject = runner.Runner()
        original = player.find_players
        player.find_players = lambda *a, **k: fake_players(["mpv"])

        async def fake_exec(*command, **kwargs):
            return FakeProcess(returncode=1)

        original_exec = asyncio.create_subprocess_exec
        asyncio.create_subprocess_exec = fake_exec
        try:
            session = await subject.start("/dev/video0", 9999, 9999, 30, None)
            await asyncio.sleep(0.05)
            self.assertFalse(session.running)
            self.assertIsNotNone(session.error)
            self.assertIn("exited", session.error)
        finally:
            asyncio.create_subprocess_exec = original_exec
            player.find_players = original


class StopTest(unittest.IsolatedAsyncioTestCase):
    async def test_stop_is_safe_when_nothing_is_running(self):
        await runner.Runner().stop()  # must not raise

    async def test_a_player_that_ignores_terminate_is_killed(self):
        subject = runner.Runner()

        class Stubborn(FakeProcess):
            def terminate(self):
                pass  # ignores SIGTERM, as mpv does with the DRM master

            async def wait(self):
                # Hang until killed, which is the only way to make the grace
                # period expire and reach the kill path.
                while not self.killed:
                    await asyncio.sleep(0.01)
                return self.returncode

        stubborn = Stubborn()

        async def fake_exec(*command, **kwargs):
            return stubborn

        original_exec = asyncio.create_subprocess_exec
        original_players = player.find_players
        asyncio.create_subprocess_exec = fake_exec
        player.find_players = lambda *a, **k: fake_players(["mpv"])
        try:
            await subject.start("/dev/video0", 1280, 720, 60, None)
            # Shorten the grace period so the test does not wait three seconds.
            original_grace = runner.TERMINATE_GRACE
            runner.TERMINATE_GRACE = 0.05
            try:
                await subject.stop()
            finally:
                runner.TERMINATE_GRACE = original_grace
            self.assertTrue(stubborn.killed)
            self.assertIsNone(subject.session)
        finally:
            asyncio.create_subprocess_exec = original_exec
            player.find_players = original_players


if __name__ == "__main__":
    unittest.main()