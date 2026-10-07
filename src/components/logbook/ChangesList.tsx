import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import {
  boxText,
  changeFacts,
  changeSummary,
  changeSummaryText,
  unknownParams,
  unknownParamsNote,
  type ChangeFacts,
} from "@/lib/logbook/changes";
import type { RunChange } from "@/lib/logbook/types";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Width of the kind column — TASK, BOX, SETTING — so facts line up down the page. */
const KIND_COL = "76px";

/**
 * What changed since each animal's previous run (`DATA.md#what-changed`) —
 * the facts a notebook most often fails to record because nobody thought them
 * worth writing down at the time.
 *
 * One row per animal with something to report, the animal's colour at its
 * edge — the same colour it has in the performance table above and in
 * Analytics. Inside, each fact on its own line under a kind label, old value
 * then new, the new one bright: the eye finds "what is it now" first. Settings
 * are a small table so the keys and values align. Animals with nothing to
 * report are named once underneath rather than given an empty row each.
 */
export function ChangesList({
  changes,
  names,
  colors,
}: {
  changes: RunChange[];
  names: Map<string, string>;
  colors: Map<string, string>;
}) {
  const nameOf = (change: RunChange) => names.get(change.animalId) ?? change.animalId;
  const rows = [...changes]
    .map((change) => ({ change, facts: changeFacts(change) }))
    .sort((a, b) => collator.compare(nameOf(a.change), nameOf(b.change)));
  const changed = rows.filter((row) => row.facts.any);
  const unchanged = rows.filter((row) => !row.facts.any);
  const note = unknownParamsNote(unknownParams(changes));

  if (changes.length === 0) {
    return <p className="px-4 py-4 text-[12px] text-static">No runs recorded yet.</p>;
  }
  if (changed.length === 0) {
    return (
      <div className="px-4 py-4 text-[12px] text-static">
        <p>
          Nothing changed: every animal ran the same task
          {note ? "" : ", box and parameters"} as its previous run.
        </p>
        {note && <p className="mt-1 text-[11px] text-static/70">{note}</p>}
      </div>
    );
  }

  return (
    <div>
      <ul className="divide-y divide-halo/70">
        {changed.map(({ change, facts }) => (
          <li
            key={change.runId}
            className="relative grid grid-cols-[150px_1fr] gap-x-5 py-3 pr-4 pl-5"
          >
            <span
              aria-hidden
              className="absolute inset-y-2.5 left-0 w-[3px] rounded-r-full"
              style={{ background: colors.get(change.animalId) ?? "var(--color-halo)" }}
            />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate text-[13px] text-starlight">{nameOf(change)}</span>
              <span
                className="font-mono text-[10px] text-static"
                title={
                  change.box === null
                    ? "Recovered from a file, which records the port it used but not the box"
                    : undefined
                }
              >
                {boxText(change.box)}
              </span>
            </div>
            <Facts facts={facts} task={change.task} />
          </li>
        ))}
      </ul>
      {unchanged.length > 0 && (
        <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-halo/70 px-5 py-2.5 text-[11px] text-static">
          <Kind>unchanged</Kind>
          <span data-selectable>{unchanged.map(({ change }) => nameOf(change)).join(", ")}</span>
        </p>
      )}
      {note && <p className="px-5 pb-3 text-[11px] text-static/70">{note}</p>}
    </div>
  );
}

/**
 * The tile header's one fact: how many animals changed, as a count in Pulsar
 * when there is anything to count, then what kind of changes they were.
 */
export function ChangesStatus({ changes }: { changes: RunChange[] }) {
  const summary = changeSummary(changes);
  const text = changeSummaryText(summary);
  if (summary.changed === 0) return <>{text}</>;
  const [head, ...rest] = text.split(" · ");
  return (
    <>
      <span className="rounded-sm bg-pulsar px-1.5 py-px font-mono text-[10px] text-void">
        {head}
      </span>
      {rest.length > 0 && <span>{rest.join(" · ")}</span>}
    </>
  );
}

function Facts({ facts, task }: { facts: ChangeFacts; task: string }) {
  if (facts.first) {
    return (
      <div className="flex min-w-0 flex-col gap-1.5" data-selectable>
        <Fact kind="first run">
          <span className="text-[12px] text-starlight">{task}</span>
        </Fact>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-selectable>
      {facts.task && (
        <Fact kind="task">
          {facts.task.revised ? (
            <span className="flex flex-wrap items-center gap-2 text-[12px]">
              <span className="text-starlight">{facts.task.to}</span>
              <span className="rounded-sm border border-pulsar/60 px-1 py-px font-mono text-[9px] tracking-[0.1em] text-pulsar uppercase">
                definition revised
              </span>
            </span>
          ) : (
            <Delta from={facts.task.from} to={facts.task.to} />
          )}
        </Fact>
      )}
      {facts.box && (
        <Fact kind="box">
          <Delta from={facts.box.from} to={facts.box.to} mono />
        </Fact>
      )}
      {facts.params.length > 0 && (
        <div
          className="grid items-baseline gap-x-3 gap-y-1"
          style={{ gridTemplateColumns: `${KIND_COL} max-content max-content max-content minmax(0, 1fr)` }}
        >
          {facts.params.map((param, index) => (
            <ParamRow key={param.key} param={param} first={index === 0} count={facts.params.length} />
          ))}
        </div>
      )}
      {facts.counted && (
        <Fact kind="also">
          <span className="text-[11px] text-static">{facts.counted}</span>
        </Fact>
      )}
    </div>
  );
}

function Fact({ kind, children }: { kind: string; children: ReactNode }) {
  return (
    <div className="grid items-baseline gap-x-3" style={{ gridTemplateColumns: `${KIND_COL} minmax(0, 1fr)` }}>
      <Kind>{kind}</Kind>
      {children}
    </div>
  );
}

function Kind({ children }: { children: ReactNode }) {
  return (
    <span className="font-mono text-[10px] tracking-[0.12em] whitespace-nowrap text-static uppercase">
      {children}
    </span>
  );
}

/** Old value, arrow, new value — the new one is what the reader came for. */
function Delta({ from, to, mono = false }: { from: string; to: string; mono?: boolean }) {
  const face = mono ? "font-mono text-[11px]" : "text-[12px]";
  return (
    <span className={`flex min-w-0 flex-wrap items-baseline gap-x-2 ${face}`}>
      <span className="text-static break-all">{from}</span>
      <Arrow />
      <span className="text-starlight break-all">{to}</span>
    </span>
  );
}

function Arrow() {
  return (
    <ArrowRight
      size={11}
      strokeWidth={2}
      className="shrink-0 translate-y-px text-pulsar"
      aria-label="to"
    />
  );
}

function ParamRow({
  param,
  first,
  count,
}: {
  param: { key: string; from: string; to: string };
  first: boolean;
  count: number;
}) {
  return (
    <>
      <span>{first && <Kind>{count === 1 ? "setting" : "settings"}</Kind>}</span>
      <span className="font-mono text-[11px] text-starlight">{param.key}</span>
      <span className="font-mono text-[11px] text-static break-all">{param.from}</span>
      <Arrow />
      <span className="font-mono text-[11px] text-starlight break-all">{param.to}</span>
    </>
  );
}
