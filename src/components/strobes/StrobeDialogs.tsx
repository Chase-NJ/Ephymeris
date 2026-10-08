import { Archive, Plus, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Callout } from "@/components/common/Callout";
import { Button, NumberInput, TextInput } from "@/components/common/controls";
import { Modal } from "@/components/common/Modal";
import { errorMessage } from "@/lib/cohorts/commands";
import {
  addStrobe,
  importVocabulary,
  removeStrobe,
  retireStrobe,
  strobeUsage,
} from "@/lib/strobes/commands";
import { useSidecar } from "@/lib/ws/context";
import {
  ERR,
  EVT,
  SidecarCommandError,
  type StrobeImportPlan,
  type StrobeScanProgress,
  type StrobeUsage,
  type StrobeVocabulary,
} from "@/lib/ws/protocol";

import { Chip, inRanges } from "./StrobeTable";

/*
 * The four dialogs that change the vocabulary.
 *
 * Each states what is PERMANENT about its edit before the button that makes it,
 * because the one thing every edit here shares is that its consequences outlive
 * the app: a recorded file carries a number forever, and the vocabulary is the
 * only record of what that number meant.
 *
 * None of them predicts a refusal. What they show — blockers, breaks, the scan
 * — is the sidecar's `strobes.usage`, and the command checks it all again.
 */

const NAME = /^[A-Z][A-Z0-9_]*$/;

// --------------------------------------------------------------------------- //
// Add
// --------------------------------------------------------------------------- //

export function AddStrobeDialog({
  open,
  initialCode,
  vocabulary,
  onClose,
}: {
  open: boolean;
  initialCode: number | null;
  vocabulary: StrobeVocabulary;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const [name, setName] = useState("");
  const [code, setCode] = useState<number | null>(null);
  const [meaning, setMeaning] = useState("");
  const [emittedOn, setEmittedOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setCode(initialCode ?? vocabulary.nextFree);
    setMeaning("");
    setEmittedOn("");
    setError(null);
    // Reset on open only; a vocabulary update mid-dialog must not wipe a draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialCode]);

  /**
   * As-you-type hints. The sidecar's answer is final; these only save a trip.
   * Silent while a submit is in flight: `strobes.updated` lands before the
   * reply, and the code being added would otherwise be reported as taken by
   * itself.
   */
  const nameHint = useMemo(() => {
    if (!name || busy) return null;
    if (name.startsWith("BF_")) return "Leave off BF_ — the generated header adds it.";
    if (!NAME.test(name)) return "Upper snake case: letters, digits, underscores.";
    if (vocabulary.codes.some((c) => c.name === name)) return `${name} is already live.`;
    if (vocabulary.retired.some((c) => c.name === name))
      return `${name} is retired — reinstate it instead of issuing the name a second number.`;
    return null;
  }, [name, vocabulary, busy]);

  const codeHint = useMemo(() => {
    if (code === null || busy) return null;
    const taken =
      vocabulary.codes.find((c) => c.code === code) ??
      vocabulary.retired.find((c) => c.code === code);
    if (taken) return `${code} is ${taken.name}.`;
    if (inRanges(vocabulary.reserved, code)) return `${code} is reserved.`;
    if (code < vocabulary.codeMin || code > vocabulary.codeMax)
      return `Codes run ${vocabulary.codeMin}–${vocabulary.codeMax}: the wire carries three digits.`;
    return null;
  }, [code, vocabulary, busy]);

  const ready = !!name && !nameHint && code !== null && !codeHint && meaning.trim().length > 0;

  const submit = async () => {
    if (!ready || code === null) return;
    setBusy(true);
    setError(null);
    try {
      await addStrobe(client, {
        name,
        code,
        rationale: meaning.trim(),
        ...(emittedOn.trim() ? { emittedOn: emittedOn.trim() } : {}),
      });
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Add a strobe code">
      <div className="flex flex-col gap-3.5">
        <div className="grid grid-cols-[1fr_7rem] gap-3">
          <Field label="Name" hint={nameHint}>
            <TextInput
              label="Code name"
              mono
              autoFocus
              value={name}
              placeholder="LASER_ON"
              onChange={(v) => setName(v.toUpperCase().replace(/\s+/g, "_"))}
            />
          </Field>
          <Field label="Number" hint={codeHint}>
            <NumberInput
              label="Code number"
              integer
              value={code ?? ""}
              fallback={vocabulary.nextFree ?? ""}
              invalid={!!codeHint}
              onChange={setCode}
            />
          </Field>
        </div>
        <Field label="What it means">
          <textarea
            aria-label="What the code means"
            value={meaning}
            onChange={(e) => setMeaning(e.target.value)}
            rows={3}
            placeholder="The event, and why it is worth a code of its own."
            className="resize-none rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] leading-relaxed text-starlight placeholder:text-static/60 hover:border-static/40 focus:border-pulsar focus:outline-none"
          />
        </Field>
        <Field label="Emitted on (optional)">
          <TextInput
            label="When the firmware emits it"
            value={emittedOn}
            placeholder="e.g. the laser's rising edge"
            onChange={setEmittedOn}
          />
        </Field>

        <Callout
          title="Permanent once recorded"
          tone="warning"
          why={
            <>
              The first session that records{" "}
              <span className="font-mono text-starlight">{name || "this code"}</span> fixes its
              number for good: from then on it can be retired but never removed or reused. Every
              generated sketch is rebuilt with it; firmware emits it as{" "}
              <span className="font-mono text-starlight">BF_{name || "NAME"}</span>.
            </>
          }
        />

        {error && <p className="text-[11.5px] text-status-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!ready || busy} onClick={() => void submit()}>
            <Plus size={13} strokeWidth={1.75} />
            {busy ? "Adding…" : "Add code"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

// --------------------------------------------------------------------------- //
// Retire
// --------------------------------------------------------------------------- //

export function RetireDialog({
  usage,
  onClose,
}: {
  usage: StrobeUsage | null;
  onClose: () => void;
}) {
  return (
    <Modal open={usage !== null} onClose={onClose} title={`Retire ${usage?.name ?? ""}?`}>
      {usage && <RetireBody key={usage.name} usage={usage} onClose={onClose} />}
    </Modal>
  );
}

function RetireBody({ usage, onClose }: { usage: StrobeUsage; onClose: () => void }) {
  const { client } = useSidecar();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** What the sidecar found naming the code after this dialog opened. */
  const [late, setLate] = useState<StrobeUsage | null>(null);
  const shown = late ?? usage;
  const named = shown.breaks.length > 0 || shown.firmware.length > 0;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      // Confirm exactly what was shown. Anything that started naming the code
      // since comes back as STROBE_WOULD_BREAK_TASKS, and is shown in turn.
      await retireStrobe(client, usage.name, named);
      onClose();
    } catch (err) {
      if (err instanceof SidecarCommandError && err.code === ERR.STROBE_WOULD_BREAK_TASKS) {
        const detail = err.detail as Pick<StrobeUsage, "breaks" | "firmware">;
        setLate({ ...usage, breaks: detail.breaks ?? [], firmware: detail.firmware ?? [] });
      }
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3.5">
      <p className="text-[13px] leading-relaxed text-static">
        <span className="font-mono text-starlight">{usage.code}</span>{" "}
        <span className="font-mono text-starlight">{usage.name}</span> stops being a live code. Its
        number stays <span className="text-starlight">reserved forever</span> and is never issued
        again, so every recorded file that carries it keeps decoding as{" "}
        <span className="font-mono">{usage.name}</span>.
      </p>
      <Callout
        title="What retiring does"
        tone="warning"
        why="Generated headers stop defining it. Firmware that still emits it will no longer compile — on purpose: an event the vocabulary says nothing produces should not reach the archive. It can be reinstated later under the same name and number."
      />
      <UsageLists usage={shown} verb="retired" />
      {error && <p className="text-[11.5px] text-status-error">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button variant="primary" disabled={busy} onClick={() => void submit()}>
          <Archive size={13} strokeWidth={1.75} />
          {busy ? "Retiring…" : named ? "Retire anyway" : "Retire code"}
        </Button>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Remove
// --------------------------------------------------------------------------- //

export function RemoveDialog({
  name,
  onClose,
  onRetireInstead,
}: {
  name: string | null;
  onClose: () => void;
  onRetireInstead: (usage: StrobeUsage) => void;
}) {
  const { client } = useSidecar();
  const [usage, setUsage] = useState<StrobeUsage | null>(null);
  const [progress, setProgress] = useState<StrobeScanProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The scan starts the moment the dialog opens: the answer it gives is the
  // whole decision, and asking the operator to click "check" first would put
  // a confirm button on screen before anyone knew whether it was allowed.
  useEffect(() => {
    if (!name) return;
    let cancelled = false;
    setUsage(null);
    setProgress(null);
    setError(null);
    const off = client.on(EVT.STROBES_SCAN_PROGRESS, (data) => {
      if (!cancelled) setProgress(data as StrobeScanProgress);
    });
    void strobeUsage(client, name, true)
      .then((u) => {
        if (!cancelled) setUsage(u);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      });
    return () => {
      cancelled = true;
      off();
    };
  }, [client, name]);

  const submit = async () => {
    if (!usage) return;
    setBusy(true);
    setError(null);
    try {
      await removeStrobe(client, usage.name, usage.breaks.length > 0 || usage.firmware.length > 0);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const scanned = usage?.sessions?.scanned;
  const refused = usage?.removeBlocker ?? null;

  return (
    <Modal open={name !== null} onClose={onClose} title={`Remove ${name ?? ""}?`}>
      <div className="flex flex-col gap-3.5">
        <p className="text-[13px] leading-relaxed text-static">
          Removing deletes the code and returns its number to the free pool. That is only safe
          for a code <span className="text-starlight">no recorded session has ever contained</span>,
          so every session this machine can reach is checked first.
        </p>

        {!usage && !error && <ScanProgress progress={progress} />}

        {usage && refused && (
          <Callout title="Removal refused" tone="error" why={refused}>
            {usage.sessions && usage.sessions.count > 0 && (
              <div className="flex flex-col gap-0.5">
                {usage.sessions.sample.map((path) => (
                  <span key={path} className="truncate font-mono text-[10px] text-static" title={path}>
                    {path}
                  </span>
                ))}
                {usage.sessions.count > usage.sessions.sample.length && (
                  <span className="text-[10px] text-static/70">
                    and {usage.sessions.count - usage.sessions.sample.length} more
                  </span>
                )}
              </div>
            )}
          </Callout>
        )}

        {usage && !refused && scanned && (
          <>
            <Callout
              title="No recorded session contains it"
              tone="warning"
              why={
                <>
                  Checked {scanned.files.toLocaleString()} recorded file
                  {scanned.files === 1 ? "" : "s"} in {scanned.roots.length} cohort folder
                  {scanned.roots.length === 1 ? "" : "s"} on this machine
                  {scanned.unreadable > 0 && <>, {scanned.unreadable} unreadable</>}
                  {scanned.unreachableRoots.length > 0 && (
                    <>, {scanned.unreachableRoots.length} not reachable</>
                  )}
                  . Another machine's archive is <span className="text-starlight">not</span>{" "}
                  checked — if this code was ever used on another rig, retire it instead.
                </>
              }
            >
              {scanned.unreachableRoots.map((root) => (
                <span key={root} className="truncate font-mono text-[10px] text-static" title={root}>
                  unreachable: {root}
                </span>
              ))}
            </Callout>
            <UsageLists usage={usage} verb="removed" />
          </>
        )}

        {error && <p className="text-[11.5px] text-status-error">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          {usage && refused && usage.status === "live" && usage.retireBlocker === null && (
            <Button variant="secondary" onClick={() => onRetireInstead(usage)}>
              <Archive size={13} strokeWidth={1.75} />
              Retire instead
            </Button>
          )}
          {usage && !refused && (
            <Button variant="primary" disabled={busy} onClick={() => void submit()}>
              <Trash2 size={13} strokeWidth={1.75} />
              {busy ? "Removing…" : `Remove ${usage.name}`}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}

export function ScanProgress({ progress }: { progress: StrobeScanProgress | null }) {
  const fraction = progress && progress.total > 0 ? progress.done / progress.total : 0;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="h-1 overflow-hidden rounded-full bg-halo/60">
        <div
          className="h-full bg-pulsar transition-[width] duration-200"
          style={{ width: `${Math.max(fraction, progress ? 0.02 : 0) * 100}%` }}
        />
      </div>
      <span className="font-mono text-[10.5px] text-static">
        {progress
          ? `Reading recorded sessions… ${progress.done.toLocaleString()} / ${progress.total.toLocaleString()}`
          : "Finding recorded sessions…"}
      </span>
    </div>
  );
}

/** What names the code: saved tasks it would break, and firmware that emits it. */
export function UsageLists({ usage, verb }: { usage: StrobeUsage; verb: string }) {
  if (usage.breaks.length === 0 && usage.firmware.length === 0) return null;
  return (
    <Callout
      title={`Named by ${usage.breaks.length + usage.firmware.length} thing${usage.breaks.length + usage.firmware.length === 1 ? "" : "s"}`}
      tone="warning"
      why={`Each of these stops compiling once ${usage.name} is ${verb}, until it no longer names the code.`}
    >
      {usage.breaks.map((b) => (
        <div key={b.specId} className="flex items-baseline gap-2 text-[11px]">
          <Chip>task</Chip>
          <span className="text-starlight">{b.label ?? b.specId}</span>
          <span className="ml-auto font-mono text-[10px] text-static">{b.codes.join(" ")}</span>
        </div>
      ))}
      {usage.firmware.map((f) => (
        <div key={`${f.kind}-${f.path}`} className="flex items-baseline gap-2 text-[11px]">
          <Chip>{f.kind}</Chip>
          <span className="truncate font-mono text-[10.5px] text-static" title={f.path}>
            {f.path}
          </span>
        </div>
      ))}
    </Callout>
  );
}

// --------------------------------------------------------------------------- //
// Import
// --------------------------------------------------------------------------- //

export function ImportDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { client } = useSidecar();
  const [document, setDocument] = useState<unknown>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [plan, setPlan] = useState<StrobeImportPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDocument(null);
    setFileName(null);
    setPlan(null);
    setError(null);
  }, [open]);

  const pick = async (file: File | undefined) => {
    if (!file) return;
    setFileName(file.name);
    setPlan(null);
    setError(null);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      setDocument(parsed);
      setPlan((await importVocabulary(client, parsed, false)).plan);
    } catch (err) {
      setDocument(null);
      setError(err instanceof SyntaxError ? "That file is not JSON." : errorMessage(err));
    }
  };

  const apply = async () => {
    if (!document) return;
    setBusy(true);
    setError(null);
    try {
      await importVocabulary(client, document, true);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const nothing = plan && plan.adds.length === 0 && plan.retires.length === 0 && plan.conflicts.length === 0;

  return (
    <Modal open={open} onClose={onClose} title="Import a vocabulary" size="lg">
      <div className="flex flex-col gap-3.5">
        <p className="text-[13px] leading-relaxed text-static">
          Bring in the codes another machine has and this one lacks. An import is a{" "}
          <span className="text-starlight">union</span>: nothing here is removed, and a code
          retired there is retired here too. Any disagreement — one name with two numbers, one
          number with two names — refuses the whole import.
        </p>
        <label className="flex cursor-pointer items-center gap-2 self-start rounded-sm border border-halo bg-nebula px-3 py-1.5 text-[12px] text-static transition-colors hover:border-static/70 hover:text-starlight">
          <Upload size={13} strokeWidth={1.75} />
          {fileName ?? "Choose an exported vocabulary…"}
          <input
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => void pick(e.target.files?.[0])}
          />
        </label>

        {plan && plan.conflicts.length > 0 && (
          <Callout
            title={`${plan.conflicts.length} conflict${plan.conflicts.length === 1 ? "" : "s"} — nothing can be imported`}
            tone="error"
            why="The two machines have issued a number differently. Resolve it on one of them first; picking a winner here would relabel one machine's recorded data."
          >
            {plan.conflicts.map((c) => (
              <span key={`${c.name}-${c.code}`} className="font-mono text-[10.5px] text-static">
                {c.message}
              </span>
            ))}
          </Callout>
        )}
        {plan && plan.adds.length > 0 && (
          <Callout title={`${plan.adds.length} to add`}>
            {plan.adds.map((a) => (
              <div key={a.name} className="flex items-baseline gap-2 font-mono text-[11px]">
                <span className="w-10 text-right text-static">{a.code}</span>
                <span className="text-starlight">{a.name}</span>
                {a.retired && <Chip>retired</Chip>}
              </div>
            ))}
          </Callout>
        )}
        {plan && plan.retires.length > 0 && (
          <Callout
            title={`${plan.retires.length} to retire`}
            tone="warning"
            why="Retired on the other machine, live here. Retiring travels: some session there contains the code and its emitter is gone."
          >
            {plan.retires.map((r) => (
              <div key={r.name} className="flex items-baseline gap-2 font-mono text-[11px]">
                <span className="w-10 text-right text-static">{r.code}</span>
                <span className="text-starlight">{r.name}</span>
              </div>
            ))}
          </Callout>
        )}
        {nothing && (
          <p className="text-[12px] text-static">
            Nothing to import — this machine already has every code in that file.
          </p>
        )}
        {plan && plan.onlyHere.length > 0 && (
          <p className="text-[11px] text-static/80">
            {plan.onlyHere.length} code{plan.onlyHere.length === 1 ? "" : "s"} exist only here and
            stay as they are.
          </p>
        )}

        {error && <p className="text-[11.5px] text-status-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!plan || plan.conflicts.length > 0 || !!nothing || busy}
            onClick={() => void apply()}
          >
            {busy ? "Importing…" : "Import"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] tracking-wider text-static uppercase">{label}</span>
      {children}
      {hint && <span className="text-[10.5px] text-status-warning">{hint}</span>}
    </div>
  );
}
