import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { errorMessage } from "@/lib/cohorts/commands";
import { springPanel } from "@/lib/motion";
import { getStrobes } from "@/lib/taskdef/commands";
import { useSidecar } from "@/lib/ws/context";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

/**
 * The strobe vocabulary — every code this rig can record, and what it means.
 *
 * A TASK PAGE. It sat under Rig for a while on the argument that a code is a
 * fact about what the hardware can REPORT, in the same way a pin is a fact
 * about what it can drive. That symmetry is real and it is not the one that
 * matters: a pin is compile-time INPUT to the firmware every task generates and
 * belongs to the box, while a code is what a *condition is named by* — the
 * onset picker one page away in the trial table is the only surface in the app
 * that consumes this table, and an operator reaches for it mid-sentence while
 * typing a trial row. Rig keeps the pins; the codes travel with the task that
 * declares them.
 *
 * READ-ONLY, DELIBERATELY. The registry is **append-only**: four years of
 * recorded sessions carry these numbers, so a code is never renumbered, never
 * repurposed and never deleted. Renaming one here would silently reinterpret
 * every historical file that carries it — the kind of edit that produces
 * confident wrong numbers rather than an error. What a future version can offer
 * is ADDING a code from `freeRanges`; nothing else is safe, and offering an
 * edit that must be refused is worse than not offering it.
 *
 * The retired section is the part worth having on screen. Those codes are
 * neither live nor free — a third state — and a reader looking at a legacy
 * session needs to be told "retired", which is an explanation, rather than
 * "unknown", which is a question.
 */
export function TaskStrobes() {
  const { client, status } = useSidecar();
  const navigate = useNavigate();
  const [vocabulary, setVocabulary] = useState<StrobeVocabulary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "connected") return;
    void getStrobes(client).then(setVocabulary).catch((e) => setError(errorMessage(e)));
  }, [client, status]);

  const free = useMemo(
    () =>
      (vocabulary?.freeRanges ?? [])
        .map(([lo, hi]) => (lo === hi ? `${lo}` : `${lo}–${hi}`))
        .join(", "),
    [vocabulary],
  );

  return (
    <div className="relative h-full">
      <SkyBackdrop />
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none absolute inset-0 overflow-y-auto p-4 pl-8"
      >
        {/* The way back, which this page went without while it was a Rig
            sub-page and the wiring editor beside it had one. A door leads
            somewhere; a room with no handle is a dead end. */}
        <Button variant="ghost" onClick={() => navigate("/task")}>
          <ArrowLeft size={13} strokeWidth={1.75} />
          Task
        </Button>
        <h1 className="pb-1 pt-2 font-display text-[22px] text-starlight">
          Strobe vocabulary
        </h1>
        <p className="max-w-prose pb-4 text-[12px] leading-relaxed text-static">
          Every event a box can report, and the number it reports it with. The
          registry is <strong className="text-starlight">append-only</strong>: a
          code is never renumbered and never repurposed, because the recorded
          archive carries these numbers and reissuing one would merge two
          unrelated event types in any analysis that spans the change. A code
          whose firmware is gone but whose sessions are on disk moves to{" "}
          <em>retired</em> below and stays reserved for good.
        </p>

        {error && <p className="text-[12px] text-status-error">{error}</p>}

        {vocabulary && (
          // Animated because it mounts a round trip after the page: without an
          // entrance the tables pop in over the already-settled heading.
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springPanel}
            className="flex max-w-[880px] flex-col gap-3"
          >
            <div className="hud rounded-md px-3.5 py-2.5 text-[11px] text-static">
              <span className="text-starlight">{vocabulary.codes.length}</span>{" "}
              codes in use ·{" "}
              <span className="text-starlight">{vocabulary.retired.length}</span>{" "}
              retired and reserved · free to issue:{" "}
              <span className="font-mono text-static/80">{free}</span>
              <p className="mt-1.5 text-[10px] leading-relaxed text-static/70">
                A code above {vocabulary.codeMax} cannot be recorded at all —
                the strobe is written as three digits and the host's parser
                reads no more, so a fourth would be dropped in silence.
              </p>
            </div>

            <Table
              title="In use"
              rows={vocabulary.codes.map((c) => ({
                code: c.code,
                name: c.name,
                detail: c.emittedOn ?? c.rationale ?? "",
                origin: c.origin,
              }))}
            />

            <Table
              title="Retired — reserved forever, never reissued"
              rows={vocabulary.retired.map((c) => ({
                code: c.code,
                name: c.name,
                detail: "emitted by firmware this build no longer contains",
                origin: "retired",
              }))}
              muted
            />
          </motion.div>
        )}
      </motion.div>
    </div>
  );
}

function Table({
  title,
  rows,
  muted,
}: {
  title: string;
  rows: { code: number; name: string; detail: string; origin: string }[];
  muted?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <section className="hud rounded-md">
      <header className="border-b border-halo px-3.5 py-2 text-[12px] font-medium text-starlight">
        {title}
      </header>
      <div className="scrollbar-none max-h-[52vh] overflow-y-auto">
        <table className="w-full border-collapse text-[11px]">
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.origin}-${row.code}`}
                className={`border-b border-halo/50 last:border-b-0 ${muted ? "opacity-60" : ""}`}
              >
                <td className="w-14 px-3.5 py-1.5 text-right font-mono text-static/80">
                  {row.code}
                </td>
                <td className="w-56 px-2 py-1.5 font-mono text-starlight">{row.name}</td>
                <td className="px-2 py-1.5 text-static/70">{row.detail}</td>
                <td className="w-24 px-3.5 py-1.5 text-right font-mono text-[10px] text-static/50">
                  {row.origin}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
