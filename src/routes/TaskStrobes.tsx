import { save } from "@tauri-apps/plugin-dialog";
import { writeTextFile } from "@tauri-apps/plugin-fs";
import { motion } from "framer-motion";
import { ArrowLeft, Download, Plus, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import { Callout } from "@/components/common/Callout";
import { Button } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { CodeMap } from "@/components/strobes/CodeMap";
import {
  AddStrobeDialog,
  ImportDialog,
  RemoveDialog,
  RetireDialog,
} from "@/components/strobes/StrobeDialogs";
import { StrobeDetail } from "@/components/strobes/StrobeDetail";
import {
  rangeSize,
  rowsOf,
  StrobeTable,
  type StrobeFilter,
} from "@/components/strobes/StrobeTable";
import { errorMessage } from "@/lib/cohorts/commands";
import { SAVE_STEPS, trackExport } from "@/lib/exports/jobs";
import { springPanel } from "@/lib/motion";
import { exportVocabulary } from "@/lib/strobes/commands";
import { useStrobeVocabulary } from "@/lib/strobes/useStrobeVocabulary";
import { useSidecar } from "@/lib/ws/context";
import type { StrobeUsage } from "@/lib/ws/protocol";

/**
 * The strobe vocabulary — every code this machine can record, and the one
 * place any of them is defined (`TASKS.md#strobe-vocabulary`).
 *
 * A TASK PAGE, not a Rig one: a pin is compile-time input that belongs to the
 * box, while a code is what a *condition is named by* — the trial table's
 * onset picker is its main consumer, and an operator reaches for this table
 * mid-sentence while typing a trial row.
 *
 * EDITABLE, WITH THE ARCHIVE AS THE JUDGE. Every number here is carried by
 * recorded files, so the edits that are safe are the ones that cannot change
 * what a recorded number means: issuing a FREE number to a NEW name, rewording
 * a meaning, retiring a code (its number stays reserved), reinstating one, and
 * removing a code no recorded session contains. Renumbering and renaming are
 * not offered at all. The sidecar enforces every rule; this page shows its
 * reasons rather than predicting them.
 */
const FETCHING = "Fetching the vocabulary";

export function TaskStrobes() {
  const { client } = useSidecar();
  const navigate = useNavigate();
  const { vocabulary, error } = useStrobeVocabulary();

  const [filter, setFilter] = useState<StrobeFilter>("live");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ code: number | null } | null>(null);
  const [retiring, setRetiring] = useState<StrobeUsage | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const rows = useMemo(() => (vocabulary ? rowsOf(vocabulary) : []), [vocabulary]);
  const row = rows.find((r) => r.name === selected) ?? null;

  // A code removed (or one whose row the filter now hides) drops the
  // selection rather than leaving the detail describing a row nobody can see.
  useEffect(() => {
    if (selected && !rows.some((r) => r.name === selected)) setSelected(null);
  }, [rows, selected]);
  // Follow the selected row when it is selected, or when retiring or
  // reinstating moves it across the filter — but not when the filter itself
  // changes, which must still be able to hide it.
  useEffect(() => {
    if (row && filter !== "all" && row.status !== filter) setFilter("all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, row?.status]);

  const editable = vocabulary?.editable ?? false;

  // Reported on the export card (`ARCHITECTURE.md#export-progress`), like the
  // app's other exports — including its failures.
  const doExport = () =>
    trackExport("Strobe vocabulary", "json", [FETCHING, ...SAVE_STEPS], async (tracker) => {
      const reply = await exportVocabulary(client).catch((err: unknown) => {
        throw new Error(errorMessage(err));
      });
      tracker.step(SAVE_STEPS[0]);
      const path = await save({
        defaultPath: reply.filename,
        filters: [{ name: "Strobe vocabulary", extensions: ["json"] }],
      });
      if (!path) return null;
      tracker.step(SAVE_STEPS[1]);
      await writeTextFile(path, `${JSON.stringify(reply.document, null, 2)}\n`);
      return path;
    }).catch(() => undefined);

  return (
    <div className="relative h-full">
      <SkyBackdrop />
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="absolute inset-0 flex flex-col gap-3 p-4 pl-8"
      >
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          <div className="flex flex-col">
            <Button variant="ghost" className="self-start" onClick={() => navigate("/task")}>
              <ArrowLeft size={13} strokeWidth={1.75} />
              Task
            </Button>
            <h1 className="pt-2 font-display text-[22px] text-starlight">Strobe vocabulary</h1>
            <p className="max-w-prose pt-0.5 text-[12px] leading-relaxed text-static">
              Every event a box can report, and the number it reports it with. This is the only
              place a code is defined: every generated sketch and every task profile reads it.
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" disabled={!editable} onClick={() => setImporting(true)}>
              <Upload size={13} strokeWidth={1.75} />
              Import
            </Button>
            <Button variant="ghost" disabled={!vocabulary} onClick={() => void doExport()}>
              <Download size={13} strokeWidth={1.75} />
              Export
            </Button>
            <Button
              variant="primary"
              disabled={!editable}
              onClick={() => setAdding({ code: null })}
            >
              <Plus size={13} strokeWidth={1.75} />
              Add code
            </Button>
          </div>
        </div>

        {error && <p className="text-[12px] text-status-error">{error}</p>}
        {vocabulary && !vocabulary.editable && (
          <Callout
            title="This machine's vocabulary cannot be read"
            tone="error"
            why={
              <>
                {vocabulary.problem} Codes are being decoded with the shipped default, and every
                edit is refused until the file is repaired — a code issued now could reuse a
                number this machine already gave to something else.
              </>
            }
          />
        )}

        {vocabulary && (
          <>
            <motion.section
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={springPanel}
              className="hud flex flex-col gap-2 rounded-md px-4 py-3"
            >
              <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[11px] text-static">
                <Stat value={vocabulary.codes.length} label="live" />
                <Stat value={vocabulary.retired.length} label="retired, reserved" />
                <Stat
                  value={rangeSize(vocabulary.freeRanges)}
                  label="free"
                />
                <span className="ml-auto font-mono text-[10.5px] text-static/70">
                  next free {vocabulary.nextFree ?? "—"} · max {vocabulary.codeMax}, a three-digit
                  wire limit
                </span>
              </div>
              <CodeMap
                vocabulary={vocabulary}
                selected={row?.code ?? null}
                onSelectCode={(code) => {
                  const hit = rows.find((r) => r.code === code);
                  if (hit) setSelected(hit.name);
                }}
                onPickFree={(code) => editable && setAdding({ code })}
              />
            </motion.section>

            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={springPanel}
              className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_340px]"
            >
              <StrobeTable
                rows={rows}
                filter={filter}
                query={query}
                selected={selected}
                onFilter={setFilter}
                onQuery={setQuery}
                onSelect={setSelected}
              />
              {row ? (
                <StrobeDetail
                  row={row}
                  editable={editable}
                  version={vocabulary.contentHash + row.meaning + (row.emittedOn ?? "")}
                  onRetire={setRetiring}
                  onRemove={setRemoving}
                />
              ) : (
                <aside className="hud flex items-center justify-center rounded-md px-6 text-center text-[11.5px] leading-relaxed text-static/70">
                  Select a code to see what it means, what emits it, and whether any recorded
                  session contains it.
                </aside>
              )}
            </motion.div>
          </>
        )}
      </motion.div>

      {vocabulary && (
        <AddStrobeDialog
          open={adding !== null}
          initialCode={adding?.code ?? null}
          vocabulary={vocabulary}
          onClose={() => setAdding(null)}
        />
      )}
      <RetireDialog usage={retiring} onClose={() => setRetiring(null)} />
      <RemoveDialog
        name={removing}
        onClose={() => setRemoving(null)}
        onRetireInstead={(usage) => {
          setRemoving(null);
          setRetiring(usage);
        }}
      />
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
    </div>
  );
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <span>
      <span className="font-mono text-[13px] text-starlight">{value.toLocaleString()}</span>{" "}
      {label}
    </span>
  );
}
