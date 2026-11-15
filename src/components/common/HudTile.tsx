import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/**
 * One subject, as a HUD tile — `SummaryCard`'s header grammar (pulsar icon,
 * label, one mono fact on the right) over that subject's working surface.
 *
 * Born as the Rig tab's private `RigTile` and lifted here when Settings took
 * the same shape: two pages drawing the same header from two copies is how
 * one of them drifts by a pixel and the app grows a second grammar.
 *
 * Not `SummaryCard` itself: that component's body is a row list with its own
 * padding and its header can be a destination, while these bodies are forms
 * that manage their own edges and the header goes nowhere. Not `SettingGroup`
 * either — its title sits *outside* the card, which read as a document; the
 * HUD idiom puts the name on the glass.
 */
export function HudTile({
  icon: Icon,
  label,
  status,
  children,
}: {
  icon: LucideIcon;
  label: string;
  /** One live fact, in the header's right corner. A node rather than a string
   *  so a fact can carry its state's colour — the Boxes tile's health dots. */
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="hud overflow-hidden rounded-md">
      <div className="flex items-center gap-3 border-b border-halo px-4 py-3">
        <Icon size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
        <span className="text-[13px] font-medium text-starlight">{label}</span>
        {status && (
          <span className="ml-auto flex shrink-0 items-center gap-2 font-mono text-[11px] text-static">
            {status}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}
