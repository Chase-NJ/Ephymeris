import { useMemo } from "react";
import { Route, Routes, useSearchParams } from "react-router";

import { useIntanStatus } from "@/lib/intan/context";
import type { ScopeTrigger } from "@/lib/intan/windows";

import { IsiWindow } from "./IsiWindow";
import { ProbeMapWindow } from "./ProbeMapWindow";
import { PsthWindow } from "./PsthWindow";
import { SpikeScopeWindow } from "./SpikeScopeWindow";

/**
 * The root of a recording pop-up window (`main.tsx` mounts it, in place of
 * `App`, when the window opens at `#/scope/…`).
 */
export function ScopeApp() {
  return (
    <Routes>
      <Route path="/scope/spikescope" element={<SpikeScopeWindow />} />
      <Route path="/scope/psth" element={<PsthWindow />} />
      <Route path="/scope/isi" element={<IsiWindow />} />
      <Route path="/scope/probemap" element={<ProbeMapWindow />} />
    </Routes>
  );
}

export interface ScopeContext {
  box: number;
  animal: string | null;
  initialChannel: string | null;
  triggers: ScopeTrigger[];
  /** The channels this box records — empty until `intan.status` arrives. */
  channels: string[];
  sampleRate: number;
}

/** What the opening window put in the query, joined with the live recording. */
export function useScopeContext(): ScopeContext {
  const [params] = useSearchParams();
  const intan = useIntanStatus();
  const box = Number(params.get("box") ?? 0);
  const triggerText = params.get("triggers") ?? "";

  const triggers = useMemo<ScopeTrigger[]>(
    () =>
      triggerText
        .split(",")
        .map((pair) => {
          const [code, ...name] = pair.split(":");
          return { code: Number(code), name: name.join(":") };
        })
        .filter((t) => Number.isFinite(t.code) && t.name !== ""),
    [triggerText],
  );

  const mine = intan.recording?.boxes.find((b) => b.box === box);
  return {
    box,
    animal: params.get("animal"),
    initialChannel: params.get("channel"),
    triggers,
    channels: mine?.channels ?? [],
    sampleRate: intan.recording?.sampleRate ?? intan.sampleRate ?? 30000,
  };
}
