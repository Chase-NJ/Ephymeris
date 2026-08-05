import { Button } from "@/components/common/controls";
import type { ParadigmSummary } from "@/lib/specs/types";
import { ParadigmCard } from "../ParadigmCard";

/**
 * The template picker, which is now the SECONDARY path.
 *
 * `/task/new` opens straight into step 1 on the `blank` paradigm; this screen
 * is reached by a quiet "start from a template instead" link. That inverts what
 * it used to be — a mandatory gate in front of every new task — and the reason
 * is that a template is a shortcut for the seven shapes this lab already runs,
 * not a prerequisite for designing an eighth.
 *
 * The doctrine survives the inversion intact: "from scratch" is a paradigm that
 * FIXES nothing (`paradigms/blank.yaml`), not the absence of one. The generator
 * still reads every value from an authority, `specs.skeleton` is unchanged, and
 * there is still exactly one creation path.
 */
export function StartingPoints({
  paradigms,
  loading,
  onPick,
  onCancel,
}: {
  paradigms: ParadigmSummary[];
  loading: boolean;
  onPick: (paradigmId: string) => void;
  onCancel: () => void;
}) {
  // `hidden` rather than an id check: `blank` is what you get by NOT picking,
  // so listing it here would offer the default as one of the alternatives.
  const shown = paradigms.filter((p) => !p.hidden);

  return (
    <div className="scrollbar-none flex-1 overflow-y-auto px-6 py-5">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-display text-[15px] text-starlight">Start from a template</h2>
          <Button variant="ghost" onClick={onCancel}>
            Design from scratch instead
          </Button>
        </div>
        <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-static">
          {shown.length} shape{shown.length === 1 ? "" : "s"} this lab already runs. Picking
          one fills in the answers it implies — you can still change every one of them in the
          steps that follow.
        </p>

        {loading ? (
          <p className="mt-4 text-[12px] text-static">Reading the templates…</p>
        ) : shown.length === 0 ? (
          <p className="mt-4 text-[12px] text-static">
            No templates are installed, which means the compiler's registry did not ship.
            Designing from scratch still works.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {shown.map((paradigm) => (
              <ParadigmCard
                key={paradigm.id}
                paradigm={paradigm}
                onClick={() => onPick(paradigm.id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
