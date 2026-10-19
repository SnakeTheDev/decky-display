import { call } from "@decky/api";
import {
  Button,
  Dropdown,
  Focusable,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { useEffect, useMemo, useState } from "react";

interface Mode {
  width: number;
  height: number;
  fps: number;
  format: string;
}

interface Device {
  path: string;
  driver: string;
  card: string;
  can_capture: boolean;
  modes: Mode[];
}

interface Scan {
  devices: Device[];
  players: { name: string; path: string }[];
  dri: string[];
  drm_cards: string[];
}

interface Status {
  running: boolean;
  error: string | null;
  mode: { width: number; height: number; fps: number; player: string } | null;
}

/** call() is untyped for methods it does not know about, so name the shape here. */
async function backend<T>(method: string, ...args: unknown[]): Promise<T> {
  return (await call(method, ...args)) as unknown as T;
}

function formatSize(mode: Mode): string {
  return `${mode.width}x${mode.height} @ ${mode.fps} (${mode.format})`;
}

function Content() {
  const [scan, setScan] = useState<Scan | null>(null);
  const [status, setStatus] = useState<Status>({ running: false, error: null, mode: null });
  const [devicePath, setDevicePath] = useState<string>("");
  const [modeIndex, setModeIndex] = useState<number>(0);
  const [drawOnPanel, setDrawOnPanel] = useState<boolean>(false);
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const rescan = async () => {
    try {
      const result = await backend<Scan>("scan");
      setScan(result);
      setError(null);
      setDevicePath((current) =>
        current && result.devices.some((d) => d.path === current)
          ? current
          : result.devices.length > 0
            ? result.devices[0].path
            : "",
      );
    } catch (e) {
      setError(`Could not scan for capture devices: ${e}`);
    }
  };

  useEffect(() => {
    rescan();
    backend<Status>("status").then(setStatus).catch(() => undefined);
    // Only on mount. While a player holds the device, rescanning underneath it
    // would fight for it and make the list flicker.
  }, []);

  const device = useMemo(
    () => scan?.devices.find((d) => d.path === devicePath) ?? null,
    [scan, devicePath],
  );

  // A device can be unplugged with this panel open, so keep the index in range
  // rather than trusting the stored one.
  const mode = device && device.modes.length > 0
    ? device.modes[Math.min(modeIndex, device.modes.length - 1)]
    : null;

  const start = async () => {
    if (!device || !mode) return;
    setBusy(true);
    setError(null);
    try {
      const card = drawOnPanel && scan && scan.drm_cards.length > 0 ? scan.drm_cards[0] : null;
      const result = await backend<Status>(
        "start", device.path, mode.width, mode.height, mode.fps, card,
      );
      setStatus(result);
      if (result.error) setError(result.error);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    try {
      setStatus(await backend<Status>("stop"));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const noPlayer = scan !== null && scan.players.length === 0;
  const nothingPluggedIn = scan !== null && scan.devices.length === 0;
  const needsMpv = drawOnPanel && scan !== null && !scan.players.some((p) => p.name === "mpv");
  const noDrm = scan !== null && scan.drm_cards.length === 0;
  const problem = error || status.error;

  return (
    <div style={{ padding: "0 0.5rem" }}>
      <PanelSection title="Display">
        <PanelSectionRow>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <Button disabled={busy || !device || !mode} onClick={status.running ? stop : start}>
              {status.running ? "Stop" : "Use as display"}
            </Button>
            <Button disabled={busy} onClick={rescan}>
              Rescan
            </Button>
          </div>
        </PanelSectionRow>
        {status.running && status.mode && (
          <PanelSectionRow>
            <div style={{ color: "var(--decky-controls-foreground)", fontSize: "0.85em" }}>
              Showing {status.mode.width}x{status.mode.height} @ {status.mode.fps} via {status.mode.player}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {scan && scan.devices.length > 0 && (
        <PanelSection title="Source">
          <PanelSectionRow>
            <Dropdown
              selectedOption={devicePath}
              rgOptions={scan.devices.map((d) => ({
                label: d.card || d.driver || d.path,
                data: d.path,
              }))}
              onChange={(option) => setDevicePath(option.data)}
            />
          </PanelSectionRow>
          {device && device.modes.length > 0 && (
            <PanelSectionRow>
              <Dropdown
                selectedOption={mode}
                rgOptions={device.modes.map((m) => ({ label: formatSize(m), data: m }))}
                onChange={(option) => {
                  const index = device.modes.indexOf(option.data);
                  setModeIndex(index < 0 ? 0 : index);
                }}
              />
            </PanelSectionRow>
          )}
          {device && device.modes.length === 0 && (
            <PanelSectionRow>
              <div style={{ fontSize: "0.85em", opacity: 0.7 }}>
                This device reports no usable capture modes.
              </div>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <PanelSection title="Where to draw">
        <PanelSectionRow>
          <Focusable>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                type="checkbox"
                id="draw-on-panel"
                checked={drawOnPanel}
                disabled={noDrm}
                onChange={(e) => setDrawOnPanel(e.target.checked)}
                style={{ width: "1em", height: "1em" }}
              />
              <label htmlFor="draw-on-panel" className={staticClasses.Label}>
                Draw on the Deck's panel instead of a window
              </label>
            </div>
          </Focusable>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "0.8em", opacity: 0.7 }}>
            {noDrm
              ? "No DRM device found, so only windowed drawing is possible."
              : "Drawing on the panel needs mpv, and takes DRM away from gamescope, so it only works outside Game Mode. Experimental."}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {nothingPluggedIn && (
        <PanelSection title="Nothing found">
          <PanelSectionRow>
            <div style={{ fontSize: "0.85em" }}>
              No capture device found. Plug a USB HDMI capture adapter into the Deck, with the
              other machine's HDMI output going into the adapter, then press Rescan.
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {noPlayer && (
        <PanelSection title="No player installed">
          <PanelSectionRow>
            <div style={{ fontSize: "0.85em" }}>
              This Deck has no mpv, ffplay or GStreamer. Most SteamOS installs already have mpv.
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {(problem || needsMpv) && (
        <PanelSection title="Problem">
          <PanelSectionRow>
            <div style={{ fontSize: "0.85em" }}>
              {problem || "Drawing on the panel needs mpv, which is not installed."}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {scan && (
        <PanelSection title="Diagnostics">
          <PanelSectionRow>
            <div style={{ fontSize: "0.8em", opacity: 0.7, whiteSpace: "pre-wrap" }}>
              {`players: ${scan.players.length ? scan.players.map((p) => p.name).join(", ") : "none"}\n` +
                `drm: ${scan.drm_cards.length ? scan.drm_cards.join(", ") : "none"}\n` +
                `devices: ${scan.devices.length}`}
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}
    </div>
  );
}

export default Content;