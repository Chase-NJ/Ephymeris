import { useEffect, useRef, useState } from "react";

import type { SidecarClient } from "@/lib/ws/client";
import { compileSpec } from "./commands";
import { toYaml } from "./document";
import type { SpecCompileResult, SpecDocument } from "./types";

/** Trailing debounce on the live compile. ~21 ms warm on a dev machine, but
 * frozen-on-Windows cold is worse and there is no reason to compile three
 * half-states of one word. */
const DEBOUNCE_MS = 120;

/**
 * Compile the document as it changes, discarding stale replies.
 *
 * Staleness is by sequence number rather than by `corr` juggling: the WS
 * client already correlates request to reply, so all this hook must guarantee
 * is that a slow reply for edit N never overwrites the reply for edit N+1.
 * `result` keeps the LAST result while a compile is in flight — a form that
 * flashed empty between keystrokes would make the diagnostics unreadable.
 */
export function useCompile(
  client: SidecarClient,
  connected: boolean,
  doc: SpecDocument | null,
  specId: string | null,
): { result: SpecCompileResult | null; compiling: boolean; failure: string | null } {
  const [result, setResult] = useState<SpecCompileResult | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const sequence = useRef(0);

  useEffect(() => {
    if (!connected || doc === null) {
      setResult(null);
      setCompiling(false);
      return;
    }
    const mine = ++sequence.current;
    setCompiling(true);
    const timer = setTimeout(() => {
      void (async () => {
        try {
          const reply = await compileSpec(client, toYaml(doc), specId ?? undefined);
          if (sequence.current === mine) {
            setResult(reply);
            setFailure(null);
            setCompiling(false);
          }
        } catch (err) {
          if (sequence.current === mine) {
            // A transport/command failure, not a compile failure — compile
            // failures are successful replies. Keep the stale result visible
            // under the banner rather than blanking the form's context.
            setFailure(err instanceof Error ? err.message : String(err));
            setCompiling(false);
          }
        }
      })();
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [client, connected, doc, specId]);

  return { result, compiling, failure };
}
