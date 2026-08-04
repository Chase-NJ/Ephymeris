import {
  Braces,
  Columns2,
  Droplets,
  ListOrdered,
  MoveRight,
  Octagon,
  Sparkles,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { ParadigmSummary } from "@/lib/specs/types";

/**
 * One template, as a card.
 *
 * EXTRACTED BECAUSE IT EXISTED TWICE — the Task tab's empty-library hero and
 * the wizard's picker rendered the same markup with different padding, so a
 * change to one was a change somebody had to remember to make to the other.
 *
 * Each paradigm carries a glyph and an accent, which is the "visually
 * distinguish them" half. The mapping is by id and lives here rather than in a
 * paradigm file on purpose: an icon is a property of how this app draws a card,
 * not of what an experiment measures, and putting it in the registry would make
 * the compiler's data know about lucide. A paradigm with no entry falls back to
 * a neutral glyph rather than vanishing.
 */
const GLYPH: Record<string, { icon: LucideIcon; accent: string }> = {
  two_afc: { icon: Columns2, accent: "var(--color-pulsar)" },
  two_afc_unrewarded: { icon: Droplets, accent: "var(--color-series-2)" },
  shaping: { icon: MoveRight, accent: "var(--color-ion)" },
  go_nogo: { icon: Octagon, accent: "var(--color-status-warning)" },
  seq2_retention: { icon: ListOrdered, accent: "var(--color-series-4)" },
  seq3_retention: { icon: ListOrdered, accent: "var(--color-series-5)" },
  shaping_no_stimulus: { icon: Target, accent: "var(--color-series-6)" },
  blank: { icon: Sparkles, accent: "var(--color-static)" },
};

/**
 * The leading sentence of a paradigm's `affords`.
 *
 * Splits on a period followed by whitespace, so "10 ms hold and walks up" and
 * the em-dashed asides survive. A paradigm whose first sentence runs long is
 * still clamped by the CSS, so the worst case is what the card did before.
 */
function tagline(affords: string): string {
  return affords.split(/(?<=\.)\s+/)[0] ?? affords;
}

export function ParadigmCard({
  paradigm,
  onClick,
  compact = false,
}: {
  paradigm: ParadigmSummary;
  onClick: () => void;
  /** The hero's denser padding. Layout only — everything else is shared. */
  compact?: boolean;
}) {
  const { icon: Icon, accent } = GLYPH[paradigm.id] ?? {
    icon: Braces,
    accent: "var(--color-static)",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className={`group min-w-0 rounded-sm border border-halo text-left transition-colors hover:border-pulsar ${
        compact ? "px-2.5 py-2" : "px-3 py-2.5"
      }`}
    >
      <div className="flex items-center gap-2">
        <Icon size={13} strokeWidth={1.75} style={{ color: accent }} />
        <span className="min-w-0 truncate text-[12.5px] text-starlight">
          {paradigm.name}
        </span>
      </div>
      {/* THE FIRST SENTENCE, not the paragraph.
          `affords` is written for someone who has already chosen and wants to
          know what they got, and seven of those side by side turn a chooser
          into a wall of prose. Every paradigm's opening sentence is already the
          summary — "One stimulus, two ports, reward at the correct one." — so
          this needs no second field to keep in sync and throws no prose away:
          the Designer's header still carries the whole text once a task exists.
          Clamped as well, because a paradigm added later might not oblige. */}
      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-static">
        {tagline(paradigm.affords)}
      </p>
    </button>
  );
}
