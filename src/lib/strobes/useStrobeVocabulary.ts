import { useCallback, useEffect, useState } from "react";

import { errorMessage } from "@/lib/cohorts/commands";
import { useSidecar } from "@/lib/ws/context";
import { EVT, type StrobeVocabulary } from "@/lib/ws/protocol";

import { getVocabulary } from "./commands";

/**
 * This machine's strobe vocabulary, kept current.
 *
 * The vocabulary is editable now, so no copy of it may be held past the next
 * `strobes.updated`: the trial table's onset picker reading a stale one would
 * offer a code that was just retired. The event carries the whole vocabulary,
 * so it replaces the copy rather than prompting a refetch.
 */
export function useStrobeVocabulary(): {
  vocabulary: StrobeVocabulary | null;
  error: string | null;
  reload: () => void;
} {
  const { client, status } = useSidecar();
  const [vocabulary, setVocabulary] = useState<StrobeVocabulary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (status !== "connected") return;
    let cancelled = false;
    void getVocabulary(client)
      .then((v) => {
        if (cancelled) return;
        setVocabulary(v);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(errorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [client, status, tick]);

  useEffect(
    () =>
      client.on(EVT.STROBES_UPDATED, (data) => {
        setVocabulary(data as StrobeVocabulary);
      }),
    [client],
  );

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { vocabulary, error, reload };
}
