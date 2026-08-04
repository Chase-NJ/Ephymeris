import { motion } from "framer-motion";
import { ArrowLeft, CpuIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { Button, Select } from "@/components/common/controls";
import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { BoardBench } from "@/components/specs/BoardBench";
import { PANEL_TRAVEL, springPanel } from "@/lib/motion";
import { useCompile } from "@/lib/specs/useCompile";
import { useSpecDocument } from "@/lib/specs/useSpecDocument";
import { useSpecs } from "@/lib/specs/useSpecs";
import { useSidecar } from "@/lib/ws/context";

/**
 * Bench — a compiled table, a board, and nothing that resembles a session.
 *
 * Its own route rather than a panel inside the Designer, for the reason the
 * warning strip states: this is the one surface in the app that talks to real
 * hardware about a spec, and it must not read as one more section of an editor.
 * Arriving here is a deliberate act, and the page says what it is before it
 * says what it can do.
 *
 * THE NO-SESSION INVARIANT IS STRUCTURAL, not a matter of this page's restraint.
 * No wire command ties a spec to a session: `sessions.confirmMapping` never
 * learns a `specId`, `port.startSession` is untouched, and `UPLOADING ↔
 * IN_SESSION` is illegal in the transition table in both directions. That door
 * opens at Task-Graph Phase 5's exit criteria, not by adding a button here.
 *
 * The spec arrives as `?spec=<id>` from the Designer and is otherwise picked
 * here — the compile is re-run either way, because the table a board receives
 * is compiled from this document server-side and never taken on trust.
 */
export function TaskBench() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const { client, status } = useSidecar();
  const connected = status === "connected";
  const { specs, unavailable } = useSpecs();

  const [specId, setSpecId] = useState<string | null>(params.get("spec"));
  const session = useSpecDocument(specId);
  const { result } = useCompile(client, connected, session.doc, specId);

  /*
   * Keep the query string honest, so a reload or a shared link lands back on
   * the same board/spec pairing the operator was looking at.
   *
   * GATED ON STILL BEING THE CURRENT ROUTE. `setSearchParams` writes to
   * whatever location is current, not to the one this component was rendered
   * for — and an exiting route stays mounted for the length of its transition,
   * so an unguarded write here stamped `?spec=…` onto whichever page had
   * already replaced this one. It followed the operator all the way to
   * `/cohorts`. Writing only when the value actually differs also keeps this
   * from pushing a history entry per render.
   */
  useEffect(() => {
    if (location.pathname !== "/task/bench") return;
    if ((params.get("spec") ?? null) === specId) return;
    setParams(specId ? { spec: specId } : {}, { replace: true });
  }, [specId, params, setParams, location.pathname]);

  return (
    <div className="relative h-full">
      <SkyBackdrop opacity={0} />

      <motion.div
        initial={{ opacity: 0, y: PANEL_TRAVEL }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none absolute inset-0 overflow-y-auto"
      >
        <section className="mx-auto max-w-3xl px-8 py-8">
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={() => navigate("/task")} title="Back to Task">
              <ArrowLeft size={13} strokeWidth={1.75} />
            </Button>
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <CpuIcon size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <h1 className="font-display text-[22px] text-starlight">Bench</h1>
          </div>

          {unavailable ? (
            <p
              className="surface mt-6 rounded-md px-4 py-3.5 text-[12px] leading-relaxed"
              style={{ color: "var(--color-status-warning)" }}
            >
              {unavailable}
            </p>
          ) : (
            <section className="surface mt-6 rounded-md">
              <div className="flex flex-wrap items-start justify-between gap-6 border-b border-halo px-4 py-3.5">
                <p className="min-w-0 max-w-prose text-[12px] leading-relaxed text-static">
                  Choose a task spec, then probe and load a board. The table is
                  compiled here, on this machine, from the spec as it is saved —
                  a board is never sent a table a client assembled.
                </p>
                <Select
                  label="Task spec"
                  value={specId ?? ""}
                  options={[
                    { value: "", label: "— select a spec —" },
                    ...specs.map((s) => ({
                      value: s.specId,
                      label: s.label ? `${s.specId} — ${s.label}` : s.specId,
                    })),
                  ]}
                  onChange={(v) => setSpecId(v === "" ? null : String(v))}
                  disabled={!connected}
                  className="w-[240px] shrink-0 truncate"
                />
              </div>

              <div className="px-4 py-3.5">
                {specId && session.doc ? (
                  <BoardBench
                    specId={specId}
                    doc={session.doc}
                    compiled={result?.ok === true && result.table !== null}
                  />
                ) : (
                  <p className="text-[12px] leading-relaxed text-static">
                    {specId
                      ? "Opening the spec…"
                      : "Select a spec to see the bench boxes."}
                  </p>
                )}
              </div>
            </section>
          )}
        </section>
      </motion.div>
    </div>
  );
}
