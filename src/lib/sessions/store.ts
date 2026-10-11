/**
 * Client-side mirror of prefix and live-session state.
 *
 * Independent slices with keyed subscriptions, same shape as
 * `HardwareStore`: the prefix list (fed by `prefixes.updated`, replayed on
 * connect), per-box live telemetry (fed by `session.telemetry`, which is
 * pushed per metric update rather than batched — far lower frequency than raw
 * strobes, per `PROTOCOL.md#evt-session.telemetry`), and the active-session answer
 * (queried via `sessions.active` on connect, kept live by `session.lifecycle`).
 *
 * It also notices on its own when a run begins, and forgets the last one: no
 * caller tells it, because a caller can only guess when the sidecar's run
 * began, and Debug Mode's guess came before a START that could still be
 * refused (`ARCHITECTURE.md#live-session-views`). See `attach` for the three events.
 */

import type { SidecarPort } from "../ws/port";
import { CMD, EVT } from "../ws/protocol";
import type {
  ActiveSessions,
  AnimalEnded,
  Prefix,
  TelemetryMetric,
} from "./types";

const NO_PREFIXES: Prefix[] = [];
const NO_METRICS: TelemetryMetric[] = [];
const NO_HISTORY: number[] = [];
const NO_STROBES: StrobeEvent[] = [];

/** Enough points for a legible trace over a long session, not unbounded. */
const HISTORY_LIMIT = 240;

/**
 * How many strobes to keep per box. A real session emits a few thousand
 * (2,711 in the reference archive run), so this holds a whole session with
 * room to spare while staying bounded — the point being that the live panels
 * must not lose their early trials the way the sidecar's capped passthrough
 * ring (~2000 lines) would make them.
 */
const STROBE_LIMIT = 20000;

const STROBE_LINE = /^(\d{1,3})\t(\d+)$/;

/** One decoded strobe: the code the board sent and its session-relative ms. */
export interface StrobeEvent {
  code: string;
  at: number;
}

export class SessionStore {
  private prefixes: Prefix[] = NO_PREFIXES;
  /** Latest rolling metrics per box. */
  private telemetry = new Map<number, TelemetryMetric[]>();
  /**
   * Recent values per box per metric, oldest first.
   *
   * The sidecar pushes only the current rolling value, so the shape of the
   * session over time exists nowhere else — this is what the live charts draw.
   */
  private history = new Map<number, Map<string, number[]>>();
  /** Finished runs this session, per box. */
  private ended = new Map<number, AnimalEnded>();
  /**
   * The latest failure to write a box's session files (`sidecar.error` with a
   * `detail.box`) — a file that would not open, or a strobe that could not be
   * appended. The box may keep running, so this is the only place the operator
   * learns its data is not reaching disk.
   */
  private writeErrors = new Map<number, string>();
  /**
   * Boxes running a task started by hand from Debug Mode, on the sidecar's
   * word (`port.telemetry`). Never set from a click: the task ends when the
   * BOARD says so, a trial boundary after `STOP`, and a button that flipped
   * this itself would show "ended" over a task still delivering odor.
   */
  private debugRunning = new Set<number>();
  /**
   * Every strobe this box has emitted, in order.
   *
   * Deliberately a second consumer of `port.output` alongside `HardwareStore`:
   * that store keeps a *console* (capped at 2000 lines, trimmed oldest-first),
   * which is right for scrollback and wrong for a session-long derivation.
   * Kept as decoded `{code, at}` pairs rather than lines so a full session
   * costs little, and mutated in place with a version counter rather than
   * copied per 20 Hz batch.
   */
  private strobes = new Map<number, StrobeEvent[]>();
  private strobeVersion = 0;
  /**
   * The global "what is running?" answer — queried on every connect (the
   * ask-don't-replay pattern, `ARCHITECTURE.md#replay-on-connect`) and replaced wholesale by each
   * `session.lifecycle` broadcast. Note `running.boxes[].running` inside it
   * is point-in-time; live per-box state comes from `port.state`.
   */
  private active: ActiveSessions | null = null;
  private activeLoaded = false;
  /**
   * Boxes whose port is `IN_SESSION`, on `port.state`'s word. Only for telling
   * a run still being written apart from a mapping no box has started.
   */
  private live = new Set<number>();
  /** The running slot of the last active answer, as JSON, to tell a repeat. */
  private shownRunning: string | null = null;
  /** A box entered `IN_SESSION` since that answer. */
  private ranSinceShown = false;
  private subs = new Map<string, Set<() => void>>();

  attach(client: SidecarPort): () => void {
    let detached = false;
    let broadcasts = 0;
    const ask = () => {
      const seen = broadcasts;
      client
        .call(CMD.SESSIONS_ACTIVE)
        .then((result) => {
          if (detached) return;
          // A broadcast landed while this was in flight, and either may be the
          // newer: the sidecar can read part of this answer before a transition
          // and send it after that transition's broadcast. Ask again rather than
          // roll the screen back (`ARCHITECTURE.md#replay-on-connect`).
          if (broadcasts !== seen) {
            ask();
            return;
          }
          this.takeActive(result);
        })
        .catch(() => {
          // A failed discovery just leaves activeLoaded false; the next
          // reconnect or lifecycle broadcast will fill it in.
        });
    };
    const offs = [
      client.on(EVT.SESSION_LIFECYCLE, (data) => {
        broadcasts += 1;
        this.takeActive(data);
      }),

      // A session run begins: the box's last run, Debug or session, is not
      // this one's. A connect replays every box with `prev` equal to `state`,
      // which is no transition, so a running box keeps what it has gathered.
      client.on(EVT.PORT_STATE, (d) => {
        if (typeof d?.box !== "number") return;
        if (d.state !== "IN_SESSION") {
          this.live.delete(d.box);
          return;
        }
        this.live.add(d.box);
        if (d.prev === "IN_SESSION") return;
        this.ranSinceShown = true;
        this.forgetBox(d.box);
      }),

      client.onStatus((status) => {
        if (status === "connected") ask();
      }),

      client.on(EVT.PREFIXES_UPDATED, (data) => {
        this.prefixes = data?.prefixes ?? NO_PREFIXES;
        this.notify("prefixes");
      }),

      client.on(EVT.SESSION_TELEMETRY, (d) => {
        if (typeof d?.box !== "number") return;
        this.telemetry.set(d.box, d.metrics ?? NO_METRICS);
        this.appendHistory(d.box, d.metrics ?? NO_METRICS);
        this.notify(`telemetry:${d.box}`);
      }),

      // Debug Mode's counterpart to the above (`debug_run.py`). Same slot, same
      // history: a port in PASSTHROUGH cannot also be IN_SESSION, so the two
      // sources can never be writing one box at once, and sharing the slot is
      // what lets Debug Mode mount Mission Control's own components unchanged.
      //
      // The sidecar arms a Debug run only once its START is on the wire, so
      // the arm (running false -> true) is when the last run is forgotten; a
      // refused START never arms and leaves it on screen.
      client.on(EVT.PORT_TELEMETRY, (d) => {
        if (typeof d?.box !== "number") return;
        if (d.running && !this.debugRunning.has(d.box)) this.forgetBox(d.box);
        this.telemetry.set(d.box, d.metrics ?? NO_METRICS);
        this.appendHistory(d.box, d.metrics ?? NO_METRICS);
        if (d.running) this.debugRunning.add(d.box);
        else this.debugRunning.delete(d.box);
        this.notify(`telemetry:${d.box}`);
        this.notify(`debug:${d.box}`);
      }),

      client.on(EVT.PORT_OUTPUT, (d) => {
        if (typeof d?.box !== "number" || !d.lines?.length) return;
        let log = this.strobes.get(d.box);
        let added = false;
        for (const line of d.lines) {
          if (line.dir !== "rx") continue;
          const match = STROBE_LINE.exec(line.text.trim());
          if (!match) continue;
          if (!log) {
            log = [];
            this.strobes.set(d.box, log);
          }
          log.push({ code: match[1]!, at: Number(match[2]) });
          added = true;
        }
        if (!added || !log) return;
        if (log.length > STROBE_LIMIT) log.splice(0, log.length - STROBE_LIMIT);
        this.strobeVersion += 1;
        this.notify(`strobes:${d.box}`);
        this.notify("strobes");
      }),

      client.on(EVT.SIDECAR_ERROR, (d) => {
        const box = (d?.detail as { box?: unknown } | null)?.box;
        if (typeof box !== "number" || typeof d?.message !== "string") return;
        this.writeErrors.set(box, d.message);
        this.notify(`writeError:${box}`);
      }),

      client.on(EVT.SESSION_ANIMAL_ENDED, (d) => {
        if (typeof d?.box !== "number") return;
        this.ended.set(d.box, d);
        this.notify(`ended:${d.box}`);
        this.notify("ended");
      }),
    ];
    return () => {
      detached = true;
      offs.forEach((off) => off());
    };
  }

  // --- active session ---------------------------------------------------

  getActive(): ActiveSessions | null {
    return this.active;
  }

  activeIsLoaded(): boolean {
    return this.activeLoaded;
  }

  // --- prefixes ---------------------------------------------------------

  getPrefixes(): Prefix[] {
    return this.prefixes;
  }

  // --- live session -----------------------------------------------------

  isDebugRunning(box: number): boolean {
    return this.debugRunning.has(box);
  }

  getTelemetry(box: number): TelemetryMetric[] {
    return this.telemetry.get(box) ?? NO_METRICS;
  }

  getEnded(box: number): AnimalEnded | null {
    return this.ended.get(box) ?? null;
  }

  getWriteError(box: number): string | null {
    return this.writeErrors.get(box) ?? null;
  }

  /** One metric's recent values for a box, oldest first. */
  getHistory(box: number, metricId: string): number[] {
    return this.history.get(box)?.get(metricId) ?? NO_HISTORY;
  }

  /**
   * A box's strobes so far. The array is **mutated in place** as more arrive —
   * subscribe to `strobes:<box>` (or `strobes`) and read `getStrobeVersion()`
   * as the snapshot, then read this inside the render that version triggers.
   * Returning a fresh copy per 20 Hz batch would mean copying thousands of
   * entries several times a second for no benefit.
   */
  getStrobes(box: number): StrobeEvent[] {
    return this.strobes.get(box) ?? NO_STROBES;
  }

  /** Bumped whenever any box's strobe log grows — the render trigger. */
  getStrobeVersion(): number {
    return this.strobeVersion;
  }

  private appendHistory(box: number, metrics: TelemetryMetric[]): void {
    let perMetric = this.history.get(box);
    if (!perMetric) {
      perMetric = new Map();
      this.history.set(box, perMetric);
    }
    for (const metric of metrics) {
      if (metric.value === null) continue;
      const series = [...(perMetric.get(metric.id) ?? NO_HISTORY), metric.value];
      perMetric.set(
        metric.id,
        series.length > HISTORY_LIMIT ? series.slice(-HISTORY_LIMIT) : series,
      );
    }
  }

  /**
   * Take a new active answer, broadcast or asked for, and forget the last run
   * if it shows a newly confirmed mapping.
   *
   * The payload carries no confirmation id, so "newly confirmed" is read from
   * what it does carry: a mapping none of whose boxes has started (the runner
   * clears `startedAt` and `ended` only when a mapping is confirmed), which is
   * either not the one last shown, or the same one again after a box has run
   * since. Confirming the same group twice, with a per-box start and its end
   * in between, repeats the last broadcast exactly, and only that run tells
   * them apart. A repeat with no run between is some other announce (a
   * session created, a tidy) and changes nothing.
   */
  private takeActive(next: ActiveSessions): void {
    const shown = JSON.stringify(next.running);
    if (
      this.noneStarted(next.running) &&
      (shown !== this.shownRunning || this.ranSinceShown)
    ) {
      this.forgetRun();
    }
    this.shownRunning = shown;
    this.ranSinceShown = false;
    this.active = next;
    this.activeLoaded = true;
    this.notify("active");
  }

  /**
   * A mapping is held and no box of it has begun a run. A box still
   * `IN_SESSION` on its port has: the runner lets go of a run before its
   * files are written and its port is released, and an announce landing then
   * reads as never started.
   */
  private noneStarted(running: ActiveSessions["running"]): boolean {
    if (!running?.groupId || running.boxes.length === 0) return false;
    return running.boxes.every(
      (b) => !b.running && b.startedAt === null && !b.ended && !this.live.has(b.box),
    );
  }

  /** Forget every box's run: a new group's boxes were confirmed. */
  private forgetRun(): void {
    this.telemetry.clear();
    this.history.clear();
    this.ended.clear();
    this.writeErrors.clear();
    this.strobes.clear();
    this.strobeVersion += 1;
    this.notify("strobes");
    for (const key of this.subs.keys()) {
      if (key.startsWith("telemetry:") || key.startsWith("ended") || key.startsWith("writeError:")) {
        this.notify(key);
      }
    }
  }

  /** Forget one box's run: it began another. */
  private forgetBox(box: number): void {
    this.telemetry.delete(box);
    this.history.delete(box);
    this.ended.delete(box);
    this.writeErrors.delete(box);
    this.strobes.delete(box);
    this.strobeVersion += 1;
    this.notify(`strobes:${box}`);
    this.notify("strobes");
    this.notify(`telemetry:${box}`);
    this.notify(`ended:${box}`);
    this.notify(`writeError:${box}`);
    this.notify("ended");
  }

  // --- subscriptions ----------------------------------------------------

  subscribe(key: string, callback: () => void): () => void {
    let set = this.subs.get(key);
    if (!set) {
      set = new Set();
      this.subs.set(key, set);
    }
    set.add(callback);
    return () => {
      set.delete(callback);
    };
  }

  private notify(key: string): void {
    const set = this.subs.get(key);
    if (!set) return;
    for (const callback of set) callback();
  }
}
