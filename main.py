import asyncio
import os
import sys

import decky

sys.path.insert(0, os.path.dirname(__file__))
from py_modules.decky_display import player as player_module  # noqa: E402
from py_modules.decky_display import runner, v4l2  # noqa: E402


class Plugin:
    """Use the Deck's own screen as a display for another machine.

    The Deck is not a display adapter. There is no USB display class gadget in
    Linux and the Deck's USB-C only sends DisplayPort, so it cannot receive video
    over the cable. What works is the other way round: a USB capture adapter
    takes the other machine's HDMI output and appears on the Deck as an ordinary
    camera, and the other machine sees a real monitor because it really is
    driving one. Nothing needs installing on the other machine, which is why this
    works with whatever it happens to be.
    """

    async def _main(self) -> None:
        self._runner = runner.Runner(log=decky.logger.info)
        decky.logger.info("decky-display loaded")

    async def _unload(self) -> None:
        # Leaving a player running would keep the DRM master and the video device
        # held, so the next start would fail for a reason the user cannot see.
        await self._stop()

    async def _uninstall(self) -> None:
        await self._stop()

    async def _stop(self) -> None:
        runner_instance = getattr(self, "_runner", None)
        if runner_instance is not None:
            await runner_instance.stop()

    # --- called from the frontend -------------------------------------------------

    async def scan(self) -> dict:
        """Capture devices, players and DRM cards. Safe to call at any time."""
        devices = [device.as_dict() for device in v4l2.scan()]
        environment = player_module.describe_environment()
        environment["drm_cards"] = runner.drm_cards()
        return {"devices": devices, **environment}

    async def start(self, device: str, width: int, height: int, fps: float,
                    drm_device: str | None = None) -> dict:
        try:
            await self._runner.start(device, int(width), int(height), float(fps),
                                     drm_device or None)
        except RuntimeError as e:
            # These are user-facing conditions, not crashes: no adapter plugged
            # in, no player installed, a size the adapter will not give. Return
            # them as something to show rather than raising into the UI.
            return {"running": False, "error": str(e)}
        return self.status()

    async def stop(self) -> dict:
        await self._runner.stop()
        return self.status()

    async def status(self) -> dict:
        state = self._runner.describe()
        session = state.get("session") or {}
        return {
            "running": state["running"],
            "error": session.get("error"),
            "mode": session.get("mode"),
            "command": session.get("command"),
        }