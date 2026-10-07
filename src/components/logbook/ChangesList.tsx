import { changeParts } from "@/lib/logbook/changes";
import type { RunChange } from "@/lib/logbook/types";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/**
 * What changed since each animal's previous run (`DATA.md#what-changed`) —
 * the facts a notebook most often fails to record because nobody thought them
 * worth writing down at the time.
 */
export function ChangesList({
  changes,
  names,
  colors,
  recovered = false,
}: {
  changes: RunChange[];
  /** A recovered-files session, whose runs are never compared. */
  recovered?: boolean;
  names: Map<string, string>;
  colors: Map<string, string>;
}) {
  const rows = [...changes]
    .map((change) => ({ change, parts: changeParts(change) }))
    .sort((a, b) =>
      collator.compare(
        names.get(a.change.animalId) ?? a.change.animalId,
        names.get(b.change.animalId) ?? b.change.animalId,
      ),
    );
  const changed = rows.filter((row) => row.parts.length > 0);

  if (recovered) {
    return (
      <p className="px-4 py-4 text-[12px] text-static">
        Not compared: runs recovered from files carry no recorded parameters or box.
      </p>
    );
  }
  if (changes.length === 0) {
    return <p className="px-4 py-4 text-[12px] text-static">No runs recorded yet.</p>;
  }
  if (changed.length === 0) {
    return (
      <p className="px-4 py-4 text-[12px] text-static">
        Nothing changed: every animal ran the same task, box and parameters as its previous run.
      </p>
    );
  }

  return (
    <ul className="divide-y divide-halo/70">
      {changed.map(({ change, parts }) => (
        <li key={change.runId} className="grid grid-cols-[150px_1fr] gap-4 px-4 py-2.5">
          <span className="flex min-w-0 items-center gap-2 text-[12px] text-starlight">
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ background: colors.get(change.animalId) ?? "var(--color-static)" }}
              aria-hidden
            />
            <span className="truncate">{names.get(change.animalId) ?? change.animalId}</span>
            <span className="shrink-0 font-mono text-[10px] text-static">box {change.box}</span>
          </span>
          <span className="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-starlight" data-selectable>
            {parts.map((part, index) => (
              <span key={index} className={part.mono ? "font-mono text-[11px]" : ""}>
                {part.text}
              </span>
            ))}
          </span>
        </li>
      ))}
    </ul>
  );
}
