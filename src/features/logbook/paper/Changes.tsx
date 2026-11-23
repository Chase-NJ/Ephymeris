import type { ReactNode } from "react";

import {
  boxText,
  changeFacts,
  unknownParams,
  unknownParamsNote,
  type ChangeFacts,
} from "../changes";
import type { RunChange } from "../types";

import { AnimalMark, Footnote } from "./parts";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/**
 * What changed since each animal's previous run (`DATA.md#what-changed`): the
 * facts a notebook most often fails to record because nobody thought them
 * worth writing down at the time.
 *
 * A description list, one entry per animal with something to report: the old
 * value, an arrow, the new one, the new one in full ink because "what is it
 * now" is what the reader came for. Animals with nothing to report are named
 * once underneath, not given an empty entry each.
 */
export function Changes({
  changes,
  setAside,
  names,
  colors,
}: {
  changes: RunChange[];
  /** Runs set aside as false starts: compared with nothing, named once below. */
  setAside: RunChange[];
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

  return (
    <div className="text-[14.5px]">
      {changes.length === 0 && setAside.length === 0 && (
        <p className="text-ink-soft italic">No runs recorded yet.</p>
      )}
      {changes.length > 0 && changed.length === 0 && (
        <p className="text-ink-soft">
          Nothing changed: every animal ran the same task{note ? "" : ", box and parameters"} as
          its previous run.
        </p>
      )}
      {changed.length > 0 && (
        <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1.5">
          {changed.map(({ change, facts }) => (
            <div key={change.runId} className="contents">
              <dt>
                <AnimalMark name={nameOf(change)} color={colors.get(change.animalId)} />
                <div
                  className="pl-[15px] text-[12.5px] leading-tight text-ink-soft"
                  title={
                    change.box === null
                      ? "Recovered from a file, which records the port it used but not the box"
                      : undefined
                  }
                >
                  {boxText(change.box)}
                </div>
              </dt>
              <dd className="min-w-0" data-selectable>
                <Facts facts={facts} task={change.task} />
              </dd>
            </div>
          ))}
        </dl>
      )}
      {changed.length > 0 && unchanged.length > 0 && (
        <p className="mt-2 text-ink-soft">
          <span className="smallcaps text-[11.5px]">Unchanged:</span>{" "}
          <span data-selectable>{unchanged.map(({ change }) => nameOf(change)).join(", ")}.</span>
        </p>
      )}
      {note && <Footnote>{note}</Footnote>}
      {setAside.length > 0 && (
        <Footnote>
          Set aside as false start{setAside.length === 1 ? "" : "s"}, compared with nothing:{" "}
          {setAside
            .map(
              (change) =>
                `${nameOf(change)}${change.falseStartSource === "marked" ? " (by hand)" : ""}`,
            )
            .join(", ")}
          . The run after each is compared with the animal's previous session.
        </Footnote>
      )}
    </div>
  );
}

function Facts({ facts, task }: { facts: ChangeFacts; task: string }) {
  if (facts.first) {
    return (
      <Fact kind="first run">
        <span>{task}</span>
      </Fact>
    );
  }
  return (
    <div className="flex flex-col gap-0.5">
      {facts.task && (
        <Fact kind="task">
          {facts.task.revised ? (
            <>
              {facts.task.to}, <span className="text-ink-plum italic">definition revised</span>
            </>
          ) : (
            <Delta from={facts.task.from} to={facts.task.to} />
          )}
        </Fact>
      )}
      {facts.box && (
        <Fact kind="box">
          <Delta from={facts.box.from} to={facts.box.to} />
        </Fact>
      )}
      {facts.params.map((param) => (
        <Fact key={param.key} kind={<span className="lit normal-case">{param.key}</span>} literal>
          <Delta from={param.from} to={param.to} literal />
        </Fact>
      ))}
      {facts.counted && (
        <Fact kind="also">
          <span className="text-ink-soft">{facts.counted}</span>
        </Fact>
      )}
    </div>
  );
}

function Fact({
  kind,
  literal = false,
  children,
}: {
  kind: ReactNode;
  /** The kind is a parameter's own key, set as the machine wrote it. */
  literal?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <span className={literal ? "text-ink-soft" : "smallcaps text-[11.5px] text-ink-soft"}>{kind}</span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}

/** Old value, arrow, new value. */
function Delta({ from, to, literal = false }: { from: string; to: string; literal?: boolean }) {
  return (
    <span className={`break-words ${literal ? "lit" : ""}`}>
      <span className="text-ink-soft">{from}</span>
      <span className="mx-1.5 text-ink-blue" aria-label="to">
        →
      </span>
      <span className="text-ink">{to}</span>
    </span>
  );
}
