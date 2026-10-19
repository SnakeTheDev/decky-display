# Deck as Display

Use a Steam Deck's screen as a display for another machine.

**Read this first, because it is the part people get wrong.** The Deck cannot be
made into a USB display. Linux has no DisplayPort or HDMI gadget, and the Deck's
USB-C only *sends* video — it has no DisplayPort sink role. So there is no cable,
no driver and no setting that makes a PC treat the Deck as a monitor.

What does work is the other direction:

```
   other PC  ──HDMI/DP──▶  USB capture adapter  ──USB──▶  Deck
   (thinks it has a real monitor)                      (shows it)
```

The other machine is driving a real monitor, so Windows and Linux extend onto it
natively with no software installed at all. That is why this works with whatever
machine you happen to have: **nothing is installed on the other side.** A $15–30
USB HDMI capture adapter is the only requirement.

It is also why a $15 capture card on its own does most of this job. What this
plugin adds is a full-screen view on the Deck's own panel, with the resolution
and frame rate the adapter is actually capable of, instead of a capture app you
have to leave open.

## Install

1. Install [Decky Loader](https://decky.xyz).
2. Download `decky-display.zip` from the releases page.
3. In Game Mode: **? → Decky → Settings → General → Developer mode**, then
   **Developer → Install Plugin from ZIP File**.

## Use

1. Plug a USB HDMI capture adapter into the Deck.
2. Plug the other machine's HDMI output into the adapter.
3. Open the plugin, press **Rescan**, pick a mode, press **Use as display**.

If nothing is found, the plugin says so rather than showing a black screen — a
missing adapter, a missing player and an unsupported size are three different
problems and they are reported separately.

## What is verified, and what is not

Being straight about this, because most of it cannot be verified from a
development machine.

**Verified here.** 40 unit tests pass, covering the parts that do not need
hardware: V4L2 struct layouts and ioctl encoding pinned against `videodev2.h`,
pixel format handling, player discovery and precedence, command construction for
all three renderers, and every process failure path — no player installed, a
player that dies on start, a player that ignores `SIGTERM` and has to be killed,
and starting twice. The frontend type-checks and builds.

**Not verified, because there is no Steam Deck in the loop.** Nothing here has
run on a Deck, and no video has ever been displayed:

- Whether a real USB capture adapter enumerates and offers the modes expected.
- Whether `mpv` exists on your SteamOS image. Most do; the plugin probes and
  reports rather than assuming, and the Diagnostics panel says what it found.
- Whether drawing on the panel works at all. That path is experimental.

Three tests found real bugs while being written, all of which would have shipped
silently otherwise: an f-string missing its prefix, so the frame rate was passed
to mpv as the literal text `{fps:g}`; a DRM request silently ignored for players
that cannot do it, which would have drawn to a hidden window; and a GStreamer
pipeline with inconsistent separators.

## Drawing on the panel

Off by default, because it is the fragile part.

"Draw on the Deck's panel instead of a window" asks mpv for KMS output directly.
This needs DRM master, and **in Game Mode gamescope holds DRM master** — so this
cannot work in Game Mode, and attempting it there will either fail or disturb
gamescope. It is offered because in desktop mode the DRM master is free and it
gives a true fullscreen, borderless view with no window decorations getting in
the way.

## How it works

| | |
| --- | --- |
| `main.py` | Decky plugin surface: `scan`, `start`, `stop`, `status` |
| `py_modules/decky_display/v4l2.py` | V4L2 ioctls in ctypes — find devices, list their modes |
| `py_modules/decky_display/player.py` | Probe for a renderer, build its command line |
| `py_modules/decky_display/runner.py` | Start it, notice when it dies, stop it |
| `src/index.tsx` | The UI |

No native build step: the V4L2 layer is ctypes, so the plugin installs from a zip
on any machine.

### Choosing a renderer

SteamOS ships very little. `mpv` is on it because Steam uses it, GStreamer
usually is not, and neither is guaranteed across every SteamOS image. So the
plugin probes `PATH` for `mpv`, `ffplay` and `gst-launch-1.0`, in that order, and
tells you which it found. `mpv` is preferred because it takes a V4L2 device
directly and needs no filter pipeline; `ffplay` is the fallback; GStreamer is last
because its pipeline string has to be exactly right.

Only `mpv` and GStreamer have a KMS output, so a DRM request with neither
installed is refused with that explanation rather than quietly falling back to a
window that nobody is looking at.

## Limitations

- **Needs the capture adapter.** No way around it; see the top of this file.
- **Latency.** Typically 30–100 ms through a cheap adapter. Fine for a map, a
  guide or a wiki; not for a twitch shooter.
- **Resolution and rate are the adapter's.** A $15 adapter is usually 1080p30 or
  1080p60. The plugin lists what the device actually offers rather than what it
  would be nice to have.
- **Audio is not carried through.** Most capture adapters have no audio path.
- **Game Mode fullscreen is not solved.** See above.