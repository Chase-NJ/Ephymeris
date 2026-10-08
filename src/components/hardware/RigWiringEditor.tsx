import { CircleAlert, Hand, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button, Select } from "@/components/common/controls";
import { Callout } from "@/components/common/Callout";
import { FieldRow } from "@/components/common/FieldRow";
import { RowDensityContext } from "@/components/common/rowDensity";
import { BoardMap } from "@/components/hardware/BoardMap";
import {
  KINDS,
  kindColor,
  type RigChannel,
  type RigDocument,
} from "@/lib/hardware/types";
import type { RigSession } from "@/lib/hardware/useRig";

/**
 * The channel→pin editor — the working half of the wiring page.
 *
 * The centrepiece of `/config/wiring` (`routes/RigWiring.tsx`), behind the
 * Wiring door on the Rig landing. It binds a CHANNEL to a PIN: compiler input,
 * baked into every table, and wrong silently — which is why the preview round
 * trip, the problems list, and the would-break-tasks gate exist (`useRig`).
 *
 * THE SESSION AND THE SELECTION ARE THE PAGE'S, NOT THIS COMPONENT'S. The
 * wiring page also renders the pin table, and the two surfaces must read one
 * document and share one selection — a table row and a board cell that
 * disagreed about "the selected channel" would be the two-surfaces bug this
 * editor's own rail rule exists to prevent, one level up.
 *
 * THE MAP SELECTS, THE RAIL EDITS — `SpecCanvas`'s division, for the same
 * reason: two surfaces for one field eventually disagree. The rail is a fixed
 * right column rather than the resizable `InspectorRail` (that one exists for
 * strobe pickers twenty characters wide; a channel's fields are short).
 *
 * Saving stays the editor's own gesture, not the page's: everything else on
 * the Rig screen writes through `useSettings` per change, but a wiring edit
 * can break saved tasks, so it keeps its explicit Save with the preflight
 * (`RIG_WOULD_BREAK_TASKS`) in front of it.
 */
export function RigWiringEditor({
  rig,
  selected,
  onSelect,
}: {
  rig: RigSession;
  selected: string | null;
  onSelect: (channel: string | null) => void;
}) {
  const [carried, setCarried] = useState<string | null>(null);

  const doc = rig.doc;

  /** Pins a diagnostic points at, so a message has something to light up. */
  const problemPins = useMemo(() => {
    const out = new Set<number>();
    if (!doc) return out;
    for (const p of rig.problems) {
      for (const [name, entry] of Object.entries(doc.pins ?? {})) {
        if (p.location.includes(name) || p.message.includes(`'${name}'`)) {
          if (typeof entry?.index === "number") out.add(entry.index);
        }
      }
    }
    return out;
  }, [doc, rig.problems]);

  function edit(next: RigDocument) {
    rig.setDoc(next);
  }

  function movePin(channel: string, pin: number) {
    if (!doc) return;
    edit({
      ...doc,
      pins: { ...doc.pins, [channel]: { ...doc.pins[channel], index: pin } },
    });
  }

  function editChannel(name: string, patch: Partial<RigChannel>) {
    if (!doc) return;
    const current = doc.channels[name];
    if (!current) return;
    edit({
      ...doc,
      channels: { ...doc.channels, [name]: { ...current, ...patch } },
    });
  }

  /**
   * Add a channel on the lowest free pin.
   *
   * NAMED GENERICALLY AND THEN RENAMED, rather than asking for a name up front
   * in a dialog. The rail is already the place a channel's fields are edited,
   * so a new one arriving selected with its fields open is the same gesture as
   * editing an existing one — and a modal would cover the board the operator is
   * choosing a pin from.
   */
  function addChannel() {
    if (!doc) return;
    const used = new Set(Object.values(doc.pins).map((p) => p.index));
    const min = doc.pin_range?.min ?? 0;
    const max = doc.pin_range?.max ?? 53;
    let pin = min;
    while (pin <= max && used.has(pin)) pin += 1;
    if (pin > max) return;

    let n = 1;
    while (doc.channels[`channel_${n}`]) n += 1;
    const name = `channel_${n}`;

    edit({
      ...doc,
      channels: { ...doc.channels, [name]: { kind: "emitter", label: name } },
      pins: { ...doc.pins, [name]: { index: pin } },
    });
    onSelect(name);
  }

  function removeChannel(name: string) {
    if (!doc) return;
    const channels = { ...doc.channels };
    const pins = { ...doc.pins };
    delete channels[name];
    delete pins[name];
    edit({ ...doc, channels, pins });
    onSelect(null);
  }

  /**
   * Rename a channel in both halves at once.
   *
   * A CHANNEL NAME IS WHAT A SPEC REFERENCES, so this is the one edit here that
   * can break a saved task by itself — and it will show up in `breaks` as
   * TG223, which is the whole point of computing that before the write. Key
   * order is preserved because the map's reading order is the document's, and a
   * rename that shuffled the board would look like a move.
   */
  function renameChannel(from: string, to: string) {
    if (!doc || !to || to === from || doc.channels[to]) return;
    const rekey = <T,>(map: Record<string, T>): Record<string, T> =>
      Object.fromEntries(
        Object.entries(map).map(([k, v]) => [k === from ? to : k, v]),
      );
    const channels = rekey(doc.channels);
    // A reward line names the port it serves, so a renamed PORT has to be
    // followed there too or TG224 starts reporting a well that is not a channel.
    for (const entry of Object.values(channels)) {
      if (entry.well === from) entry.well = to;
    }
    edit({ ...doc, channels, pins: rekey(doc.pins) });
    onSelect(to);
  }

  /** `well` absent means "not plumbed", so clearing it DELETES the key rather
   * than setting it to undefined — `exactOptionalPropertyTypes` is right that
   * those are different, and the schema forbids `well: null`. */
  function unplumb(name: string, well: string) {
    if (!doc) return;
    const current = doc.channels[name];
    if (!current) return;
    const next = { ...current };
    if (well) next.well = well;
    else delete next.well;
    edit({ ...doc, channels: { ...doc.channels, [name]: next } });
  }

  const errors = rig.problems.length;
  const canSave = rig.dirty && errors === 0 && !rig.saving;

  return (
    <div>
      {/* The editor's own action strip — status on the left, the write
          controls on the right. */}
      <div className="flex items-center gap-3 border-b border-halo px-4 py-2.5">
        <div className="min-w-0 flex-1 font-mono text-[10px] text-static">
          {rig.status
            ? `${rig.status.board || "board"} · ${
                rig.status.custom ? "this rig's own" : "as shipped"
              } · ${rig.status.pinoutHash}`
            : "loading…"}
        </div>
        {rig.checking && (
          <span className="font-mono text-[10px] text-static">checking…</span>
        )}
        {errors > 0 && (
          <span
            className="flex items-center gap-1 font-mono text-[10px]"
            style={{ color: "var(--color-status-error)" }}
          >
            <CircleAlert size={11} strokeWidth={1.75} />
            {errors} problem{errors === 1 ? "" : "s"}
          </span>
        )}
        <Button
          variant="ghost"
          onClick={() => void rig.reset()}
          disabled={rig.saving || !rig.status?.custom}
          title="Discard this rig's wiring and use the pinout the build shipped with"
        >
          <RotateCcw size={12} strokeWidth={1.75} />
          Reset
        </Button>
        <Button variant="ghost" onClick={rig.revert} disabled={!rig.dirty}>
          Revert
        </Button>
        <Button variant="primary" disabled={!canSave} onClick={() => void rig.save(false)}>
          <Save size={12} strokeWidth={1.75} />
          {rig.saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {rig.loadError && (
        <p
          className="border-b border-halo px-4 py-2 text-[12px]"
          style={{ color: "var(--color-status-error)" }}
        >
          {rig.loadError}
        </p>
      )}

      {doc === null ? (
        <p className="px-4 py-6 text-center text-[12px] text-static">
          {rig.loadError ? "" : "Reading this rig's wiring…"}
        </p>
      ) : (
        <div className="grid grid-cols-1 items-start gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="flex min-w-0 flex-col gap-4">
            {carried !== null && (
              <div className="flex items-center gap-2 rounded-sm border border-pulsar/60 bg-pulsar/10 px-3 py-1.5 text-[11px] text-starlight">
                <Hand size={12} strokeWidth={1.75} />
                Carrying <span className="font-mono">{carried}</span> — click a pin to
                place it.
                <Button variant="ghost" onClick={() => setCarried(null)}>
                  Cancel
                </Button>
              </div>
            )}

            <BoardMap
              doc={doc}
              selected={selected}
              carried={carried}
              onSelect={onSelect}
              onCarry={setCarried}
              onMove={movePin}
              problemPins={problemPins}
            />

            <div className="flex items-center justify-between gap-3">
              <Legend />
              <Button variant="outline" onClick={addChannel}>
                <Plus size={12} strokeWidth={1.75} />
                Add a channel
              </Button>
            </div>

            {rig.problems.length > 0 && (
              <Callout title="Problems">
                {rig.problems.map((p, i) => (
                  <div key={i} className="flex gap-2 text-[11px] leading-relaxed">
                    <span
                      className="shrink-0 font-mono text-[10px]"
                      style={{ color: "var(--color-status-error)" }}
                    >
                      {p.code ?? "shape"}
                    </span>
                    <span className="min-w-0">
                      <span className="font-mono text-[10px] text-static">
                        {p.location}
                      </span>
                      <br />
                      {p.message}
                    </span>
                  </div>
                ))}
              </Callout>
            )}

            {rig.breaks.length > 0 && (
              <Callout
                title={`${rig.breaks.length} task${rig.breaks.length === 1 ? "" : "s"} would stop compiling`}
                tone="warning"
                why="A spec names channels, so this wiring is what resolves them. These bind something this change removes or moves."
              >
                {rig.breaks.map((b) => (
                  <div key={b.specId} className="flex items-baseline gap-2 text-[11px]">
                    <span className="font-mono text-starlight">{b.specId}</span>
                    <span className="text-static">{b.label}</span>
                    <span className="ml-auto font-mono text-[10px] text-static">
                      {b.codes.join(" ")}
                    </span>
                  </div>
                ))}
                <div className="flex items-center gap-2 pt-1">
                  <Button variant="secondary" onClick={() => void rig.save(true)}>
                    Save anyway
                  </Button>
                  <span className="text-[10.5px] leading-relaxed text-static">
                    Rewiring a box is your call — the app only refuses to let it
                    happen unnoticed.
                  </span>
                </div>
              </Callout>
            )}

            {rig.actionError && (
              <p className="text-[11px]" style={{ color: "var(--color-status-error)" }}>
                {rig.actionError}
              </p>
            )}
          </div>

          {/* The inspector column. `lg:sticky` so a long problems list scrolls
              under a rail that keeps the selected channel's fields in reach.
              `surface-inset`, not `.hud`: the editor sits inside a frosted tile
              now, and frosting inside frosting reads muddier than a flat lift.
              */}
          <div className="surface-inset rounded-sm px-3 py-1 lg:sticky lg:top-4">
            <RowDensityContext.Provider value="stacked">
              <ChannelInspector
                doc={doc}
                selected={selected}
                onEdit={editChannel}
                onUnplumb={unplumb}
                onRename={renameChannel}
                onRemove={removeChannel}
                onCarry={(name) => {
                  setCarried(name);
                  onSelect(name);
                }}
              />
            </RowDensityContext.Provider>
          </div>
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {KINDS.map((kind) => (
        <span key={kind} className="flex items-center gap-1.5">
          <span
            className="size-2 rounded-[2px]"
            style={{ background: kindColor(kind), opacity: 0.7 }}
          />
          <span className="font-mono text-[10px] text-static">{kind}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * The selected channel's fields.
 *
 * Deliberately narrow: pin lives on the map, and everything here is something
 * the map cannot show. `kind` is the one with teeth — it decides which template
 * slot a channel answers (D15), so changing it is how a spare line becomes a
 * second cue.
 */
function ChannelInspector({
  doc,
  selected,
  onEdit,
  onUnplumb,
  onRename,
  onRemove,
  onCarry,
}: {
  doc: RigDocument;
  selected: string | null;
  onEdit: (name: string, patch: Partial<RigChannel>) => void;
  onUnplumb: (name: string, well: string) => void;
  onRename: (from: string, to: string) => void;
  onRemove: (name: string) => void;
  onCarry: (name: string) => void;
}) {
  if (selected === null || !doc.channels[selected]) {
    return (
      <div className="flex flex-col gap-2 px-1 py-2">
        <div className="font-display text-[13px] text-starlight">Inspector</div>
        <p className="text-[11px] leading-relaxed text-static">
          Click a pin to see the channel on it. Drag one to move it, or click it and
          then click a pin — both work, and the second needs no gesture at all.
        </p>
      </div>
    );
  }

  const entry = doc.channels[selected];
  const pin = doc.pins[selected];

  return (
    <div className="flex flex-col gap-3 px-1 py-2">
      <div>
        <div className="font-mono text-[13px] text-starlight">{selected}</div>
        <div className="font-mono text-[10px] text-static">
          pin {pin?.index ?? "—"}
          {pin?.watch_bit !== undefined ? ` · watch bit ${pin.watch_bit}` : ""}
        </div>
      </div>

      <Button variant="outline" onClick={() => onCarry(selected)}>
        <Hand size={12} strokeWidth={1.75} />
        Move to a pin
      </Button>

      <label className="flex flex-col gap-1">
        <span className="text-[11px] text-starlight">Kind</span>
        <Select
          label="Kind"
          value={entry.kind}
          options={KINDS.map((k) => ({ value: k as string, label: k }))}
          onChange={(v) => onEdit(selected, { kind: v })}
        />
        <span className="text-[10px] leading-relaxed text-static">
          What this channel is FOR. The engagement port, the cue and the vacuum are
          resolved by kind rather than by name, so a template asks for "the engagement
          channel" and this is what answers. A sync channel pulses on every event, into
          the recording controller's digital input — a rig without one cannot be
          recorded from.
        </span>
      </label>

      <FieldRow
        label="Label"
        type="string"
        value={entry.label ?? ""}
        fallback=""
        baseline={entry.label ?? ""}
        onChange={(v) => onEdit(selected, { label: String(v) })}
        help="What you call it — &quot;sandalwood&quot; rather than &quot;odor line 1&quot;. The Task tab reads it back on every trial-type row, so this is where an odor gets its name. Display only: a task profile references the channel NAME, so renaming a label is free and renaming a channel is not."
        mono={false}
      />

      {entry.kind === "response" && (
        <FieldRow
          label="Port slot"
          type="int"
          value={entry.port_slot ?? 1}
          fallback={1}
          baseline={entry.port_slot ?? 1}
          min={1}
          max={7}
          onChange={(v) => onEdit(selected, { port_slot: Number(v) })}
          help="Which family of per-port strobes this port reports with. Slots 1 and 2 are the historical left/right codes; two ports on one slot are indistinguishable in the data."
        />
      )}

      {entry.kind === "reward" && (
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-starlight">Serves</span>
          <Select
            label="Serves"
            value={entry.well ?? ""}
            options={[
              { value: "", label: "— not plumbed —" },
              ...Object.entries(doc.channels)
                .filter(([, c]) => c.kind === "response")
                .map(([name]) => ({ value: name, label: name })),
            ]}
            onChange={(v) => onUnplumb(selected, v)}
          />
          <span className="text-[10px] leading-relaxed text-static">
            Which port this line delivers to. Declared so a task that rewards one well
            through the other's line is refused — a mistake that looks entirely correct
            in the listing and waters the wrong side of the box.
          </span>
        </label>
      )}

      <RenameRow name={selected} onRename={onRename} />

      {entry.rationale && (
        <p className="text-[10.5px] leading-relaxed text-static">{entry.rationale}</p>
      )}

      <Button
        variant="outline"
        onClick={() => onRemove(selected)}
        title={`Remove ${selected} from this rig`}
      >
        <Trash2 size={12} strokeWidth={1.75} />
        Remove this channel
      </Button>
    </div>
  );
}

/**
 * Rename, committed on blur.
 *
 * NOT PER KEYSTROKE, because a rename re-keys both halves of the document and
 * the map re-sorts around it — typing `l`, `e`, `f`… would move the cell out
 * from under the caret on every character. The same reason `StageTrialInput`
 * commits on blur, and the same shape.
 */
function RenameRow({
  name,
  onRename,
}: {
  name: string;
  onRename: (from: string, to: string) => void;
}) {
  const [draft, setDraft] = useState(name);
  useEffect(() => setDraft(name), [name]);

  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-starlight">Name</span>
      <input
        aria-label="Channel name"
        className="rounded-sm border border-halo bg-nebula px-2 py-1 font-mono text-[11px] text-starlight"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => (draft && draft !== name ? onRename(name, draft) : setDraft(name))}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setDraft(name);
        }}
      />
      <span className="text-[10px] leading-relaxed text-static">
        What every task calls it. Renaming one is a rename in every task that names
        it — anything that breaks is listed before the save lands.
      </span>
    </label>
  );
}
