/**
 * Task-spec domain types. Wire shapes re-export from the generated protocol
 * mirror — never re-declared by hand — plus the handful of editor-side types
 * the wire deliberately doesn't carry.
 */

export type {
  DiffHunk,
  DiffLine,
  SpecArtifact,
  SpecCapabilities,
  SpecCompileResult,
  SpecDiagnostic,
  SpecEntry,
  SpecGraph,
  SpecGraphEdge,
  SpecGraphNode,
  ParadigmQuestion,
  ParadigmSummary,
  SpecListingDiff,
  SpecOrigin,
  SpecTableSummary,
} from "@/lib/ws/protocol";

import type { CommandResultMap, SpecOverlay, SpecOverlayField } from "@/lib/ws/protocol";

/** The presentation overlay and its parts, under the names this module has
 * always used. The declarations themselves are generated — the overlay is a
 * wire shape, and a second hand-written copy of one is exactly the drift the
 * generated mirrors exist to stop. */
export type Overlay = SpecOverlay;
export type OverlayField = SpecOverlayField;
export type { SpecOverlayGroup as OverlayGroup } from "@/lib/ws/protocol";

/** The `specs.schema` reply — everything the form needs, fetched once. */
export type SpecSchema = CommandResultMap["specs.schema"];

/** The parsed spec document the form binds to. Deliberately loose — the
 * compiler is the authority on what's legal, and typing it tightly here would
 * be a second schema that drifts. */
export type SpecDocument = Record<string, unknown>;

/*
 * The two registries a picker reads *structurally* rather than by lookup.
 *
 * They stay `unknown` on the wire deliberately (see websocket-protocol.md
 * §3.6): they are vendored JSON files served verbatim, and pinning their full
 * shape here would be a third copy of a schema the compiler already owns. What
 * the form needs is the one field it actually reads off each entry, declared
 * once here instead of re-cast at every use site.
 */

/** `strobe_vocab.v1.json`, as far as the strobe picker reads it. Codes are
 * non-contiguous and resolution is always by NAME, so the map's keys are the
 * values a spec carries and the numbers are for display only. */
export interface StrobeRegistry {
  codes?: Record<
    string,
    {
      code: number;
      /** Why this code exists and what it reports. Already on the wire — the
       * vocabulary is served verbatim — and read by the explanation tile, which
       * is the first thing to want prose rather than a number. */
      rationale?: string;
      /** The hardware or behavioural event that emits it. */
      emitted_on?: string;
    }
  >;
  /** Slot number → the six per-port code names a port on that slot reports
   * with. Keys are strings because they arrive from JSON. Slots 1 and 2 are the
   * historical `_L`/`_R` families; this table is why nothing here derives a
   * code from a channel called `left_well` any more. */
  port_slots?: Record<string, Record<string, string>>;
}

/** `channels.v1.json`, as far as the channel picker reads it. `kind` is what
 * an overlay field's `channelKind` narrows against; `well` is declared on
 * reward lines so a picker can refuse to plumb the wrong side of the box
 * (the linter's TG224, honoured before the compile ever runs). */
export interface ChannelRegistry {
  channels?: Record<
    string,
    {
      kind: string;
      index: number;
      well?: string;
      port_slot?: number;
      /** Why this channel exists on the box. `ChannelMap.to_json()` has always
       * passed it through; the Rig wiring inspector reads it, and so does the
       * explanation tile. */
      rationale?: string;
    }
  >;
  /** `direction` and prose per KIND, not per channel — declaring direction per
   * channel made "a reward line that is an input" a representable mistake. */
  kinds?: Record<string, { direction?: string; doc?: string }>;
}
