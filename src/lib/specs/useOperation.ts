/**
 * Running a structural block: fetch `capabilities()` for the topology the op
 * PROPOSES, then apply the pure op with both answers in hand.
 *
 * This hook is the only place the two halves meet, and it exists so that
 * `operations.ts` can stay pure and synchronous. The op never holds a client
 * and never computes a capability — it is handed `caps` (the document's
 * current topology) and `next` (the proposed one), so the reconciliation is
 * the compiler's answer rather than the frontend's guess.
 *
 * The op is re-run on every answer change rather than mutated in place, which
 * is what lets the preflight card show a live, complete result while the
 * questions are still being answered: `runOp` fills any unanswered question
 * from its own suggestion.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSidecar } from "@/lib/ws/context";
import { getCapabilities } from "./commands";
import { topologyOf } from "./document";
import {
  proposeTopology,
  runOp,
  type OpAnswers,
  type OpInvocation,
  type OpResult,
} from "./operations";
import type {
  ChannelRegistry,
  SpecCapabilities,
  SpecDocument,
  StrobeRegistry,
} from "./types";

export interface OperationSession {
  /** Null until the proposed capabilities have arrived. */
  result: OpResult | null;
  answers: OpAnswers;
  answer: (id: string, value: unknown) => void;
  /** Every mandatory question has an answer or a usable suggestion, and the
   * op is not blocked — i.e. Apply would produce a complete document. */
  ready: boolean;
  error: string | null;
}

export function useOperation(
  invocation: OpInvocation | null,
  doc: SpecDocument,
  caps: SpecCapabilities | null,
  channels: ChannelRegistry,
  strobes: StrobeRegistry,
): OperationSession {
  const { client, status } = useSidecar();
  const [next, setNext] = useState<SpecCapabilities | null>(null);
  const [answers, setAnswers] = useState<OpAnswers>({});
  const [error, setError] = useState<string | null>(null);

  // Serialized so a proposal that is structurally identical doesn't re-ask.
  const proposalKey = useMemo(() => {
    if (invocation === null) return null;
    const proposed = proposeTopology(doc, invocation);
    return proposed === null ? "" : JSON.stringify(proposed);
    // The document identity changes on every keystroke elsewhere in the form;
    // only the proposed TOPOLOGY matters here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [invocation, JSON.stringify(topologyOf(doc) ?? {})]);

  // A fresh block starts with no answers — carrying them across would silently
  // apply one op's choice to another's identically-named question.
  useEffect(() => {
    setAnswers({});
    setError(null);
  }, [invocation]);

  useEffect(() => {
    if (proposalKey === null || caps === null) {
      setNext(null);
      return;
    }
    // No knob moves: the proposed capabilities ARE the current ones.
    if (proposalKey === "") {
      setNext(caps);
      return;
    }
    if (status !== "connected") {
      setNext(null);
      return;
    }
    let cancelled = false;
    void getCapabilities(client, JSON.parse(proposalKey) as Record<string, unknown>)
      .then((reply) => {
        if (!cancelled) {
          setNext(reply);
          setError(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setNext(null);
          setError("The compiler could not answer what this change would produce.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [client, status, proposalKey, caps]);

  const result = useMemo(() => {
    if (invocation === null || caps === null || next === null) return null;
    return runOp({ doc, caps, next, channels, strobes }, invocation, answers);
  }, [invocation, doc, caps, next, channels, strobes, answers]);

  const answer = useCallback((id: string, value: unknown) => {
    setAnswers((prev) => ({ ...prev, [id]: value }));
  }, []);

  const ready =
    result !== null &&
    result.preflight.blocked === null &&
    result.preflight.questions.every(
      (q) =>
        !q.mandatory ||
        (answers[q.id] !== undefined && answers[q.id] !== null) ||
        (q.suggested !== null && q.suggested !== undefined),
    );

  return { result, answers, answer, ready, error };
}
