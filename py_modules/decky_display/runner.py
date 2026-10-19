"""Running the renderer: start it, notice when it dies, stop it.

Kept apart from the Decky plumbing so the process handling can be reasoned about
on its own. The one rule here is that starting must never block: a user tapping
Start expects the UI to come back immediately, and a player that fails to start
has to say so rather than leave a dead switch.
"""

import asyncio
import os
import shutil
import subprocess

from . import player as player_module

# A player left running after the plugin is disabled keeps DRM resources and a
# video device open, which stops the next start working. Killing by process group
# matters because mpv will spawn no children but gst-launch can.
TERMINATE_GRACE = 3.0


class Session:
    """One running player."""

    def __init__(self, process: subprocess.Popen, command: list, mode: dict):
        self.process = process
        self.command = command
        self.mode = mode
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def describe(self) -> dict:
        return {
            "running": self.running,
            "exit_code": self.process.poll(),
            "error": self.error,
            "command": self.command,
            "mode": self.mode,
        }


class Runner:
    """Starts and stops the renderer."""

    def __init__(self, log=None):
        self.session: Session | None = None
        self._log = log or (lambda message: None)

    async def start(self, device: str, width: int, height: int, fps: float,
                    drm_device: str | None) -> Session:
        await self.stop()

        available = player_module.find_players()
        if not available:
            raise RuntimeError(
                "No video player found on this Deck. Install mpv (the one Steam "
                "usually ships) and try again.")

        chosen = player_module.choose(available, drm_device)
        if chosen is None:
            if drm_device:
                raise RuntimeError(
                    "Drawing to the panel needs mpv, which is not installed. "
                    "Switch to windowed mode, or install mpv.")
            raise RuntimeError("No usable player.")

        command = player_module.build_command(
            chosen.name, device, width, height, fps,
            fullscreen=True, drm_device=drm_device)

        self._log("starting: " + " ".join(command))
        environment = dict(os.environ)
        environment.setdefault("DISPLAY", ":0")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
                start_new_session=True)
        except OSError as e:
            raise RuntimeError(f"Could not start {chosen.name}: {e}") from e

        session = Session(process, command, {
            "device": device, "width": width, "height": height,
            "fps": fps, "drm_device": drm_device, "player": chosen.name,
        })
        self.session = session
        # Watch it in the background so a player that exits immediately -- the
        # usual outcome of asking for a mode the device will not give -- is
        # noticed and reported rather than looking like it started fine.
        asyncio.create_task(self._watch(session))
        return session

    async def _watch(self, session: Session) -> None:
        code = await session.process.wait()
        if session is self.session:
            session.error = (f"{session.mode['player']} exited with code {code}. "
                             "That usually means the capture device would not give "
                             "the requested size.")
            self._log(f"player exited: {code}")

    async def stop(self) -> None:
        session, self.session = self.session, None
        if session is None or not session.running:
            return
        try:
            session.process.terminate()
            await asyncio.wait_for(session.process.wait(), timeout=TERMINATE_GRACE)
        except asyncio.TimeoutError:
            # It ignored SIGTERM, which mpv does if it has grabbed the DRM
            # master. SIGKILL is the last resort but it is also the only way to
            # reclaim the video device.
            self._log("player ignored terminate; killing")
            try:
                session.process.kill()
                await session.process.wait()
            except ProcessLookupError:
                pass

    def describe(self) -> dict:
        return {
            "running": bool(self.session and self.session.running),
            "session": self.session.describe() if self.session else None,
        }


def drm_cards() -> list:
    """Card nodes we could try to draw on."""
    try:
        return [f"/dev/dri/{name}" for name in sorted(os.listdir("/dev/dri"))
                if name.startswith("card")]
    except OSError:
        return []