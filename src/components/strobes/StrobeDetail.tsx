import { Archive, ArchiveRestore, Pencil, ScanSearch, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button, TextInput } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { editStrobe, reinstateStrobe, strobeUsage } from "@/lib/strobes/commands";
import { useSidecar } from "@/lib/ws/context";
import { EVT, type StrobeScanProgress, type StrobeUsage } from "@/lib/ws/protocol";

import { ScanProgress } from "./StrobeDialogs";
import { Chip, type StrobeRow } from "./StrobeTable";

/**
 * One code: what it means, what uses it, and what may be done to it.
 *
 * The actions are offered with the SIDECAR'S reasons. `strobes.usage` says
 * whether retiring or removing would be refused and why; a disabled button
 * carries that sentence beside it rather than a tooltip, because "why can't I"
 * is the question, and the answer is a fact about the archive worth reading.
 *
 * The archive check is a button rather than automatic: it reads every recorded
 * session this machine can reach, and selecting a row to read its meaning
 * should not cost that.
 */
export function StrobeDetail({
  row,
  editable,
  version,
  onRetire,
  onRemove,
}: {
  row: StrobeRow;
  editable: boolean;
  /** Changes whenever the vocabulary does, so the usage is re-asked. */
  version: string;
  onRetire: (usage: StrobeUsage) => void;
  onRemove: (name: string) => void;
}) {
  const { client } = useSidecar();
  const [usage, setUsage] = useState<StrobeUsage | null>(null);
  const [scanning, setScanning] = useState(false);
  const [progress, setProgress] = useState<StrobeScanProgress | null>(null);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setUsage(null);
    setEditing(false);
    setError(null);
    void strobeUsage(client, row.name)
      .then((u) => {
        if (!cancelled) setUsage(u);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [client, row.name, version]);

  const scan = async () => {
    setScanning(true);
    setProgress(null);
    setError(null);
    const off = client.on(EVT.STROBES_SCAN_PROGRESS, (data) =>
      setProgress(data as StrobeScanProgress),
    );
    try {
      setUsage(await strobeUsage(client, row.name, true));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      off();
      setScanning(false);
    }
  };

  const reinstate = async () => {
    setError(null);
    try {
      await reinstateStrobe(client, row.name);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const live = row.status === "live";
  const sessions = usage?.sessions ?? null;

  return (
    <aside className="hud flex min-h-0 flex-col gap-4 overflow-y-auto rounded-md px-4 py-3.5 scrollbar-none">
      <header className="flex flex-col gap-1">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-[26px] leading-none text-starlight">{row.code}</span>
          <Chip>{row.status}</Chip>
          {row.portSlot !== undefined && <Chip>port slot {row.portSlot}</Chip>}
        </div>
        <span className="font-mono text-[13px] break-all text-starlight">{row.name}</span>
        <span className="font-mono text-[10.5px] text-static/70">
          {row.status === "live"
            ? `firmware emits BF_${row.name}`
            : `BF_${row.name} is no longer defined`}
          {row.origin ? ` · ${originLabel(row.origin)}` : ""}
        </span>
      </header>

      {editing ? (
        <MeaningEditor row={row} onDone={() => setEditing(false)} />
      ) : (
        <section className="flex flex-col gap-2">
          <Label>Meaning</Label>
          <p className="text-[12px] leading-relaxed text-starlight/90">
            {row.meaning || <span className="text-static">No meaning recorded.</span>}
          </p>
          {row.emittedOn && (
            <>
              <Label>Emitted on</Label>
              <p className="text-[12px] leading-relaxed text-static">{row.emittedOn}</p>
            </>
          )}
          {row.seenIn && (
            <>
              <Label>Seen in</Label>
              <p className="text-[12px] leading-relaxed text-static">{row.seenIn}</p>
            </>
          )}
          {live && editable && (
            <Button variant="ghost" className="self-start" onClick={() => setEditing(true)}>
              <Pencil size={12} strokeWidth={1.75} />
              Edit meaning
            </Button>
          )}
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <Label>Used by</Label>
        {!usage && !error && <span className="text-[11px] text-static/70">Looking…</span>}
        {usage && (
          <>
            {usage.portSlot !== null && (
              <Use kind="slot">
                the response port on slot {usage.portSlot} reports with it
              </Use>
            )}
            {usage.breaks.map((b) => (
              <Use key={b.specId} kind="task">
                {b.label ?? b.specId}
              </Use>
            ))}
            {usage.firmware.map((f) => (
              <Use key={`${f.kind}-${f.path}`} kind={f.kind}>
                <span className="font-mono text-[10.5px]" title={f.path}>
                  {f.path}
                </span>
              </Use>
            ))}
            {usage.portSlot === null && usage.breaks.length === 0 && usage.firmware.length === 0 && (
              <span className="text-[11px] text-static/80">
                {live
                  ? "Nothing on this machine names it — no firmware emits it yet."
                  : "Nothing on this machine names it."}
              </span>
            )}
          </>
        )}
      </section>

      <section className="flex flex-col gap-1.5">
        <Label>Recorded sessions</Label>
        {scanning ? (
          <ScanProgress progress={progress} />
        ) : sessions ? (
          <span className="text-[11.5px] leading-relaxed text-static">
            {sessions.count === 0 ? (
              <>
                {sessions.scanned.files === 1
                  ? "Not in the one recorded file on this machine."
                  : `Not in any of the ${sessions.scanned.files.toLocaleString()} recorded files on this machine.`}
              </>
            ) : (
              <>
                <span className="text-starlight">{sessions.count.toLocaleString()}</span> of{" "}
                {sessions.scanned.files.toLocaleString()} recorded files contain it.
              </>
            )}
          </span>
        ) : (
          <Button variant="outline" className="self-start" onClick={() => void scan()}>
            <ScanSearch size={12} strokeWidth={1.75} />
            Check the archive
          </Button>
        )}
      </section>

      {error && <p className="text-[11.5px] text-status-error">{error}</p>}

      {editable && usage && (
        <Actions
          live={live}
          usage={usage}
          onRetire={() => onRetire(usage)}
          onReinstate={() => void reinstate()}
          onRemove={() => onRemove(row.name)}
        />
      )}
    </aside>
  );
}

/**
 * Retire (or Reinstate) and Remove, with the sidecar's reasons. When one fact
 * blocks both — a port slot, the shared library — it is said once, under the
 * pair, rather than twice in a row.
 */
function Actions({
  live,
  usage,
  onRetire,
  onReinstate,
  onRemove,
}: {
  live: boolean;
  usage: StrobeUsage;
  onRetire: () => void;
  onReinstate: () => void;
  onRemove: () => void;
}) {
  const retireBlocker = live ? usage.retireBlocker : null;
  const shared = retireBlocker !== null && retireBlocker === usage.removeBlocker;
  return (
    <section className="mt-auto flex flex-col gap-2 border-t border-halo pt-3">
      <div className="flex flex-wrap gap-2">
        {live ? (
          <Button variant="outline" disabled={retireBlocker !== null} onClick={onRetire}>
            <Archive size={12} strokeWidth={1.75} />
            Retire
          </Button>
        ) : (
          <Button variant="outline" onClick={onReinstate}>
            <ArchiveRestore size={12} strokeWidth={1.75} />
            Reinstate
          </Button>
        )}
        <Button variant="outline" disabled={usage.removeBlocker !== null} onClick={onRemove}>
          <Trash2 size={12} strokeWidth={1.75} />
          Remove
        </Button>
      </div>
      {shared ? (
        <Reason>{retireBlocker}</Reason>
      ) : (
        <>
          {retireBlocker && <Reason>Retire: {retireBlocker}</Reason>}
          {usage.removeBlocker && <Reason>Remove: {usage.removeBlocker}</Reason>}
        </>
      )}
      {!usage.removeBlocker && (
        <Reason>Remove checks every recorded session on this machine first.</Reason>
      )}
    </section>
  );
}

function Reason({ children }: { children: React.ReactNode }) {
  return <p className="text-[10.5px] leading-relaxed text-static">{children}</p>;
}

function MeaningEditor({ row, onDone }: { row: StrobeRow; onDone: () => void }) {
  const { client } = useSidecar();
  const [meaning, setMeaning] = useState(row.meaning);
  const [emittedOn, setEmittedOn] = useState(row.emittedOn ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await editStrobe(client, { name: row.name, rationale: meaning, emittedOn });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-2">
      <Label>Meaning</Label>
      <textarea
        aria-label="What the code means"
        value={meaning}
        onChange={(e) => setMeaning(e.target.value)}
        rows={4}
        className="resize-none rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] leading-relaxed text-starlight hover:border-static/40 focus:border-pulsar focus:outline-none"
      />
      <Label>Emitted on</Label>
      <TextInput label="When the firmware emits it" value={emittedOn} onChange={setEmittedOn} />
      <p className="text-[10.5px] leading-relaxed text-static/80">
        Wording only. The name and number never change — recorded files carry the number, and
        analysis matches on the name.
      </p>
      {error && <p className="text-[11.5px] text-status-error">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button variant="primary" disabled={busy || !meaning.trim()} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </section>
  );
}

function Use({ kind, children }: { kind: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2 text-[11px] text-static">
      <Chip>{kind}</Chip>
      <span className="min-w-0 truncate">{children}</span>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-mono text-[10px] tracking-wider text-static/80 uppercase">{children}</span>
  );
}

function originLabel(origin: string): string {
  return (
    {
      firmware: "numbered by the lab's firmware",
      ephymeris: "declared by Ephymeris",
      operator: "added on the Strobes page",
    }[origin] ?? origin
  );
}
