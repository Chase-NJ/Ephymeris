import { useMemo } from "react";

import { KINDS, KIND_COLOR, kindColor, type RigDocument } from "@/lib/hardware/types";

/**
 * What the wiring is made of, as a strip: one segment per channel kind, each
 * as wide as its share of the channels, in the colour that kind wears on the
 * board map, in the pin table, and in every task's trial-table dropdowns.
 *
 * The Task landing's condition strip, on the Rig tab's own noun. Both exist
 * for the same reason — a landing tile has to say what the room behind it
 * holds before anyone opens it, and a count in prose ("14 channels") says how
 * many without saying what. A rig with twelve odor lines and a rig with two
 * odor lines and ten cues have the same count and are different benches.
 *
 * The legend is the same colours as words, for anyone who has not yet learned
 * them — and in `KINDS` order, which is the rail's, so the legend and the
 * editor list the kinds the same way round.
 */
export function KindStrip({ doc, className = "" }: { doc: RigDocument; className?: string }) {
  const counts = useMemo(() => {
    const out = new Map<string, number>();
    for (const channel of Object.values(doc.channels ?? {})) {
      out.set(channel.kind, (out.get(channel.kind) ?? 0) + 1);
    }
    // Declared kinds first, in rail order; anything a future document
    // invents trails behind so it still shows rather than being dropped.
    const known = KINDS.filter((k) => out.has(k)).map((k) => [k, out.get(k)!] as const);
    const extra = [...out.entries()].filter(([k]) => !(KINDS as readonly string[]).includes(k));
    return [...known, ...extra];
  }, [doc]);

  const total = counts.reduce((n, [, c]) => n + c, 0);
  if (total === 0) {
    return (
      <span className={`block font-mono text-[10px] text-static/70 ${className}`}>
        no channels declared
      </span>
    );
  }

  return (
    <span className={`block ${className}`}>
      <span className="flex h-1.5 w-full gap-px overflow-hidden rounded-sm" aria-hidden>
        {counts.map(([kind, count]) => (
          <span
            key={kind}
            className="h-full"
            style={{ flex: count, background: kindColor(kind) }}
          />
        ))}
      </span>
      <span className="mt-1 flex flex-wrap gap-x-2.5 gap-y-0.5 font-mono text-[10px]">
        {counts.map(([kind, count]) => (
          <span key={kind} className="flex items-center gap-1 text-static/80">
            <span
              className="size-1.5 rounded-full"
              style={{ background: KIND_COLOR[kind] ?? "var(--color-static)" }}
              aria-hidden
            />
            <span className="text-starlight">{count}</span> {kind}
          </span>
        ))}
      </span>
    </span>
  );
}
