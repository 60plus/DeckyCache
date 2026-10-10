import { callable, definePlugin } from "@decky/api";
import {
  ConfirmModal, DialogButton, DropdownItem, PanelSection, PanelSectionRow,
  ProgressBar, showModal, staticClasses, ToggleField,
} from "@decky/ui";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

type Disk = { path: string; token: string; model: string; serial: string; size: number; reusable: boolean; blocked: string };
type Library = { path: string; name: string; kind: string; enabled: boolean; active: boolean; error: string };
type Game = { id: string; name: string; steam: boolean; cached_bytes?: number; path?: string; mapper?: string };
type GameGroup = Game & { key: string; titles: string[] };
const SMALL_FRAGMENT_BYTES = 16 * 1024 ** 2;

function groupGames(games: Game[]): GameGroup[] {
  const groups = new Map<string, GameGroup>();
  for (const game of games) {
    const key = game.path && game.mapper ? JSON.stringify([game.mapper, game.path]) : game.id;
    const previous = groups.get(key);
    if (previous) {
      if (!previous.titles.includes(game.name)) previous.titles.push(game.name);
      previous.cached_bytes = Math.max(previous.cached_bytes ?? 0, game.cached_bytes ?? 0);
      // A shared folder is counted once. Prefer its shortest title for the cover.
      if (game.name.length < previous.name.length) {
        previous.name = game.name; previous.id = game.id; previous.steam = game.steam;
      }
    } else groups.set(key, { ...game, key, titles: [game.name] });
  }
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
}

const trackedSize = (n: number) => n >= 1024 ** 3
  ? (n / 1024 ** 3).toLocaleString("en-US", { maximumFractionDigits: 2 }) + " GiB"
  : n >= 1024 ** 2
    ? (n / 1024 ** 2).toLocaleString("en-US", { maximumFractionDigits: 1 }) + " MiB"
    : (n / 1024).toLocaleString("en-US", { maximumFractionDigits: 0 }) + " KiB";
type Status = {
  engine: "opencas" | "dm-cache";
  cache: { uuid: string; model: string; serial: string } | null;
  devices: Disk[]; libraries: Library[]; games: Game[]; games_state: "ready" | "updating" | "unavailable"; error: string;
  usage: { total: number; used: number } | null;
};
type Result = { ok: true; data: Status } | { ok: false; error: string };
const request = callable<[Record<string, unknown>], Result>("request");
const size = (n: number) => (n / 1024 ** 3).toLocaleString("en-US", { maximumFractionDigits: 1 }) + " GiB";
const note = { fontSize: 12, lineHeight: "1.5", color: "#aeb8c6", padding: "6px 0", overflowWrap: "anywhere" as const };

function Icon() {
  return <svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="2" y="17" width="19" height="5" rx="1.5" />
    <path d="M5 19.5h2M10 19.5h.01M12 13l-3-3c1.7-4.3 5.9-7 11-7 0 5.1-2.7 9.3-7 11Z" />
    <circle cx="16" cy="7" r="1.3" />
    <path d="m9 10-4 .5 3-4 4-.5M13 14l-.5 2 4-3 .5-4M8 13l-2 2" />
  </svg>;
}

function SectionDivider() {
  return <div role="separator" style={{ borderTop: "1px solid rgba(174, 184, 198, 0.28)", margin: "16px 16px 12px" }} />;
}

function SectionHeading({ title, help }: { title: string; help: ReactNode }) {
  return <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
    <div role="heading" aria-level={2} style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", whiteSpace: "nowrap" }}>{title}</div>
    <DialogButton onClick={() => showModal(<ConfirmModal strTitle={title} strDescription={help}
      bAlertDialog strOKButtonText="Close" />)} onOKActionDescription="Information"
      style={{ width: 30, minWidth: 30, height: 30, padding: 0, flexShrink: 0 }}>
      <span role="img" aria-label={"About " + title} title={"About " + title}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <circle cx="12" cy="12" r="9" /><path d="M12 10v7" /><circle cx="12" cy="7" r=".8" fill="currentColor" />
        </svg>
      </span>
    </DialogButton>
  </div>;
}

function Panel() {
  const [state, setState] = useState<Status | null>(null);
  const [selected, setSelected] = useState("");
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [changeDisk, setChangeDisk] = useState(false);
  const [showSmall, setShowSmall] = useState(false);
  const running = useRef(false);
  const refreshing = useRef(false);
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    if (running.current || refreshing.current) return;
    refreshing.current = true;
    try {
      const r = await request({ action: "status" });
      if (!alive.current) return;
      if (r.ok) setState(r.data);
      else setError(r.error);
    } catch (e) {
      if (alive.current) setError(String(e));
    } finally { refreshing.current = false; }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { alive.current = false; window.clearInterval(timer); };
  }, [refresh]);

  async function act(payload: Record<string, unknown>, label: string) {
    if (running.current) return;
    running.current = true;
    setWorking(label); setError("");
    try {
      const r = await request(payload);
      if (r.ok) {
        setState(r.data);
        if (payload.action === "format" || payload.action === "reuse") setChangeDisk(false);
      } else setError(r.error);
    } catch (e) { setError(String(e)); }
    finally { running.current = false; setWorking(""); }
  }

  const available = state?.devices.filter(d => !d.blocked) ?? [];
  const disk = available.find(d => d.path === selected) ?? available[0];
  const setup = !state?.cache || changeDisk;
  const active = state?.libraries.filter(l => l.active).length ?? 0;
  const groups = groupGames(state?.games ?? []);
  const smallGames = state?.engine === "opencas"
    ? groups.filter(game => (game.cached_bytes ?? 0) < SMALL_FRAGMENT_BYTES) : [];
  const mainGames = state?.engine === "opencas"
    ? groups.filter(game => (game.cached_bytes ?? 0) >= SMALL_FRAGMENT_BYTES) : groups;

  function gameDetails(game: GameGroup) {
    showModal(<ConfirmModal
      strTitle={game.name}
      strDescription={<>
        {game.cached_bytes !== undefined && <p>{trackedSize(game.cached_bytes)} of tracked cache data.</p>}
        {game.titles.length > 1 && <p>Shared installation folder: {game.titles.join(", ")}.</p>}
        <p>This is a partial count, not the size of the complete installation. Background reads can add data even if the game has not been launched.</p>
        <p>The cache engine cannot clear all cached data for just this game. Cached blocks are replaced automatically as space is needed.</p>
      </>}
      bAlertDialog strOKButtonText="Close"
    />);
  }

  function gameGrid(games: GameGroup[]) {
    return <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
      {games.map(game => <DialogButton key={game.key} className="DeckyCacheGame"
        onClick={() => gameDetails(game)}
        style={{ padding: 0, minWidth: 0, width: "100%", overflow: "hidden", borderRadius: 8, textAlign: "left" }}>
        {game.steam ? <img
          src={"https://cdn.cloudflare.steamstatic.com/steam/apps/" + game.id + "/header.jpg"}
          alt="" loading="lazy" style={{ display: "block", width: "100%", aspectRatio: "460/215", objectFit: "cover" }}
          onError={e => { e.currentTarget.style.display = "none"; }}
        /> : <div style={{ padding: 15, textAlign: "center", color: "#70d4b0" }}><Icon /></div>}
        <div style={{ fontSize: 12, padding: 8, lineHeight: "1.35", whiteSpace: "normal" }}>
          <div>{game.name}</div>
          {game.cached_bytes !== undefined && <div style={{ color: "#aeb8c6", marginTop: 4 }}>
            {trackedSize(game.cached_bytes)}
          </div>}
          {game.titles.length > 1 && <div style={{ color: "#aeb8c6", marginTop: 4 }}>
            Shared with {game.titles.length - 1} other titles
          </div>}
        </div>
      </DialogButton>)}
    </div>;
  }

  function clearCache() {
    if (!state?.cache) return;
    const cache = state.cache;
    showModal(<ConfirmModal
      strTitle="Clear all cached data?"
      strDescription={<>
        <p>Remove cached copies from {cache.model} for all selected library drives?</p>
        <p>Games on the HDD, the NVMe format and your settings are kept. Cache fills again as data is used.</p>
      </>}
      strOKButtonText="Clear cache" strCancelButtonText="Cancel" bDestructiveWarning
      onOK={() => void act({ action: "clear-cache", confirmed: true, cache_uuid: cache.uuid }, "Clearing cache…")}
    />);
  }

  function formatDisk() {
    if (!disk) return;
    showModal(<ConfirmModal
      strTitle="Format cache drive?"
      strDescription={<>
        <p>{disk.model} · {size(disk.size)}</p><p>Serial number: {disk.serial}</p>
        <p>All data on this drive will be erased.</p>
      </>}
      strOKButtonText="Format this drive"
      strCancelButtonText="Cancel"
      bDestructiveWarning
      onOK={() => void act({ action: "format", path: disk.path, token: disk.token }, "Formatting cache drive…")}
    />);
  }

  return <>
    {error && <PanelSection><div role="alert" style={{ ...note, color: "#ffae97" }}>{error}</div></PanelSection>}
    {working && <PanelSection><div style={note}>{working}</div><ProgressBar indeterminate /></PanelSection>}
    {!state ? <PanelSection><div style={note}>Loading drives and libraries…</div></PanelSection> : <>
      <PanelSection>
        <SectionHeading title="Cache drive" help={<>
          <p>The SSD/NVMe stores cached copies. Original games stay on the HDD and Steam updates continue to write there.</p>
          <p>The usage bar shows actual cached data. Clear cache removes these copies without formatting the NVMe. Data is cached again as it is read.</p>
          <p>Drive settings lets you reuse or format an additional SSD/NVMe. The system drive is excluded.</p>
        </>} />
        {state.cache && <>
          <div style={{ fontWeight: 600 }}>{state.cache.model}</div>
          <div style={{ ...note, color: state.error ? "#ffb48a" : "#70d4b0" }}>
            {state.error || (active ? "Active · " + active + (active === 1 ? " partition" : " partitions") : "Ready · select one or more drives below")}
          </div>
          {state.usage && <>
            <ProgressBar nProgress={100 * state.usage.used / state.usage.total} />
            <div style={note}>{size(state.usage.used)} used / {size(state.usage.total)}</div>
          </>}
          {!setup && <PanelSectionRow><div style={{ display: "flex", gap: 8 }}>
            <DialogButton disabled={!!working || !active || state.engine !== "opencas"} onClick={clearCache}
              style={{ flex: 1, minWidth: 0, padding: "8px 4px", fontSize: 13 }}>Clear cache</DialogButton>
            <DialogButton disabled={!!working} onClick={() => setChangeDisk(true)}
              style={{ flex: 1, minWidth: 0, padding: "8px 4px", fontSize: 13 }}>Drive settings</DialogButton>
          </div></PanelSectionRow>}
        </>}
        {setup && <>
          {available.length ? <>
            <PanelSectionRow><DropdownItem
              label="SSD / NVMe"
              rgOptions={available.map(d => ({ data: d.path, label: d.model + " · " + size(d.size) }))}
              selectedOption={disk?.path} disabled={!!working}
              onChange={o => setSelected(String(o.data))}
            /></PanelSectionRow>
            {disk && <div style={note}>Serial number: {disk.serial}</div>}
            {disk?.reusable && <PanelSectionRow><DialogButton disabled={!!working}
              onClick={() => void act({ action: "reuse", path: disk.path, token: disk.token }, "Connecting existing cache…")}>
              Reuse existing cache
            </DialogButton></PanelSectionRow>}
            <PanelSectionRow><DialogButton disabled={!!working} onClick={formatDisk}>Format and use</DialogButton></PanelSectionRow>
          </> : <div style={note}>Connect an additional SSD or NVMe. The system drive is excluded.</div>}
          {changeDisk && <PanelSectionRow><DialogButton disabled={!!working} onClick={() => setChangeDisk(false)}>Done</DialogButton></PanelSectionRow>}
        </>}
      </PanelSection>
      <SectionDivider />
      <PanelSection>
        <SectionHeading title="Library drives" help={<>
          <p>Select one or more partitions. Each switch is independent; all folders on a selected partition use cache.</p>
          {state.libraries.map(lib => <p key={lib.path}>{lib.name}<br />{lib.path}</p>)}
        </>} />
        {state.libraries.map(lib => <PanelSectionRow key={lib.path}>
          <ToggleField label={lib.name}
            description={lib.error || (lib.enabled && !lib.active ? "Waiting for cache" : undefined)}
            checked={lib.enabled} disabled={!!working || !state.cache}
            onChange={enabled => void act({ action: "library", path: lib.path, enabled }, "Saving drive selection…")}
          />
        </PanelSectionRow>)}
      </PanelSection>
      <SectionDivider />
      <PanelSection>
        <SectionHeading title={"Cached games" + (state.games_state === "ready" ? " · " + mainGames.length : "")} help={<>
          <p>The main list shows at least 16 MiB of tracked data per installation folder. Smaller entries are under Small fragments.</p>
          <p>These figures are partial. Unassigned data is included in the cache drive total. Background reads can add entries even if a game has not been launched.</p>
          <p>Games sharing a folder use one entry. Select a game for details. To remove all cached copies, use Clear cache above.</p>
        </>} />
        {state.games_state !== "ready"
          ? <div style={note}>{state.games_state === "unavailable" ? "Game list unavailable." : "Loading games…"}</div>
          : <>
            {mainGames.length ? gameGrid(mainGames) : <div style={note}>No cached games yet.</div>}
            {smallGames.length > 0 && <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid rgba(174, 184, 198, 0.28)" }}>
              <PanelSectionRow><DialogButton onClick={() => setShowSmall(value => !value)}>
                {showSmall ? "Hide small fragments" : "Small fragments"} · {smallGames.length}
              </DialogButton></PanelSectionRow>
              {showSmall && <div style={{ marginTop: 12 }}>{gameGrid(smallGames)}</div>}
            </div>}
          </>}
      </PanelSection>
    </>}
  </>;
}

export default definePlugin(() => ({
  name: "DeckyCache",
  titleView: <div className={staticClasses.Title}>DeckyCache</div>,
  content: <Panel />,
  icon: <Icon />,
}));
