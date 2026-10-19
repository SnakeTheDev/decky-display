"""Choosing something to draw the video, and telling it what to draw.

SteamOS ships very little. `mpv` is on it because Steam uses it, GStreamer
generally is not, and neither is guaranteed across the many SteamOS images in the
wild. So rather than hardcode a command, probe what is actually there and report
it back to the UI: a user whose deck cannot find a player should be told which
one it looked for, not shown a blank screen.

Command construction is kept free of side effects so it can be tested without any
of these programs installed, which is the only way to test it from a machine that
is not a Steam Deck.
"""

import os
import shutil

# In preference order. mpv first: it is the one SteamOS reliably has, it takes a
# V4L2 device directly, and it rescales and fullscreens without a pipeline of
# filters. ffplay is the fallback because it is small and often present alongside
# a desktop install. GStreamer last: excellent when present, but a long pipeline
# string that has to be exactly right.
PLAYERS = ("mpv", "ffplay", "gst-launch-1.0")


class Player:
    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path

    def __repr__(self) -> str:
        return f"Player({self.name!r})"


def find_players(path: str | None = None) -> list:
    """Every usable player, best first."""
    found = []
    for name in PLAYERS:
        resolved = shutil.which(name, path=path)
        if resolved:
            found.append(Player(name, resolved))
    return found


def _mpv_command(player: Player, device: str, width: int, height: int,
                 fps: float, fullscreen: bool, drm_device: str | None) -> list:
    command = [
        player.path,
        "--no-audio",             # a capture device has no sound and mpv will wait for it
        "--no-terminal",          # it must not write over the Deck's tty
        "--no-config",
        "--no-input-default-bindings",  # mpv's defaults fight with gamescope for the keyboard
        "--image-display-duration=inf",  # hold the last frame instead of exiting when the source stalls
        "--keep-open=yes",
        "--hwdec=no",             # the Deck's VAAPI decode does not help for an already-compressed source
        "--untimed",              # a live device has no timestamps worth trusting
    ]
    if fullscreen:
        command.append("--fs")
    if drm_device:
        # Render straight onto a KMS device. Needs DRM master, which gamescope
        # holds in Game Mode, so this is the experimental path.
        command += ["--vo=gpu", "--gpu-context=drm", f"-o={drm_device}"]
    else:
        command += ["--vo=gpu", "--gpu-api=opengl"]
    # Ask for a specific capture size. V4L2 will only hand over a mode it
    # supports, so this is a request rather than a command, and the device list
    # is what says whether it is possible.
    command += [f"--demuxer-lavf-o=video_size={width}x{height}"]
    if fps:
        command += [f"--demuxer-lavf-o=framerate={fps:g}"]
    command.append(device)
    return command


def _ffplay_command(player: Player, device: str, width: int, height: int,
                    fps: float, fullscreen: bool) -> list:
    # ffplay takes the capture size as input options, before -i. There is no KMS
    # output, so this is the windowed fallback only.
    command = [
        player.path,
        "-f", "v4l2",
        "-framerate", f"{fps:g}",
        "-video_size", f"{width}x{height}",
        "-i", device,
        "-vf", f"scale={width}:{height}",
    ]
    if fullscreen:
        command.append("-fs")
    return command


def _gst_command(player: Player, device: str, width: int, height: int,
                 fps: float, fullscreen: bool, drm_device: str | None) -> list:
    # Every separator is a standalone " !" argument, so caps filtering stays
    # readable and the whole pipeline is one element per argv slot.
    pipeline = ["v4l2src", f"device={device}", "!", "videoconvert", "!",
                "videoscale", "!", f"video/x-raw,width={width},height={height}"]
    if fps:
        pipeline += ["!", "videorate", "!", f"video/x-raw,framerate={int(round(fps))}/1"]
    if drm_device and fullscreen:
        pipeline += ["!", "kmssink", f"device={drm_device}"]
    else:
        pipeline += ["!", "autovideosink", "sync=false"]
    return [player.path, "-q"] + pipeline


def build_command(player_name: str, device: str, width: int, height: int,
                  fps: float, fullscreen: bool = True,
                  drm_device: str | None = None) -> list:
    """The argv for one player. Pure: no filesystem access, so it is testable."""
    # Refuse a DRM request from a player that cannot do it. Silently ignoring it
    # would hand back a windowed command while the caller believed it was drawing
    # to the panel, which looks exactly like a crash.
    if drm_device and player_name not in ("mpv", "gst-launch-1.0"):
        raise ValueError(f"{player_name} has no KMS output; it cannot drive a DRM device")
    player = Player(player_name, player_name)
    if player_name == "mpv":
        return _mpv_command(player, device, width, height, fps, fullscreen, drm_device)
    if player_name == "ffplay":
        return _ffplay_command(player, device, width, height, fps, fullscreen)
    if player_name == "gst-launch-1.0":
        return _gst_command(player, device, width, height, fps, fullscreen, drm_device)
    raise ValueError(f"no renderer named {player_name!r}")


def choose(players: list, drm_device: str | None) -> Player | None:
    """The player to use, or None.

    Asking for DRM rules out anything but mpv, because it is the only one of the
    three with a KMS output. Falling back to a windowed player while the caller
    believes it is drawing directly to the panel would look like a crash.
    """
    if not players:
        return None
    if drm_device:
        for player in players:
            if player.name == "mpv":
                return player
        return None
    return players[0]


def describe_environment(path: str | None = None) -> dict:
    """What the UI shows on the diagnostics screen."""
    players = find_players(path)
    cards = []
    try:
        for name in sorted(os.listdir("/dev/dri")):
            cards.append(name)
    except OSError:
        pass
    return {
        "players": [{"name": p.name, "path": p.path} for p in players],
        "dri": cards,
    }