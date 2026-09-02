import { ArrowRight } from "lucide-react";
import { Children } from "react";
import type { LucideIcon } from "lucide-react";

/**
 * One HUD tile: a header (icon, label, live status) over that subject's
 * at-a-glance rows.
 *
 * HUD-styled — translucent over the scene, per the docked-panel treatment
 * (dashboard.md §2.4) — because every page that uses one floats it on the
 * constellation.
 *
 * **`onOpen` is optional, and its absence is a statement.** A card with one is
 * a destination: the header is a button and carries the arrow. A card without
 * one is a *readout* — the Dashboard's Rig card, whose subject is the sky that
 * page is already showing, so there is nowhere for a header to go. Its rows
 * still act; the header just stops pretending to.
 *
 * SHARED because the Task tab grew its own flatter version of this — a 14px
 * static icon, no divider, no rows — and the two pages that are both "a column
 * of tiles over the rig's sky" stopped looking like one app. There is one tile
 * now, and the Dashboard's is the one that survived.
 */
export function SummaryCard({
  icon: Icon,
  label,
  status,
  onOpen,
  empty,
  children,
}: {
  icon: LucideIcon;
  label: string;
  /** One live fact. A node rather than a string so it can carry its state's
   *  colour — the Boxes tile's health dots (`HudTile` makes the same call). */
  status: React.ReactNode;
  onOpen?: () => void;
  empty: string | null;
  children?: React.ReactNode;
}) {
  const heading = (
    <>
      <Icon size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
      <span className="text-[13px] font-medium text-starlight">{label}</span>
      <span className="ml-auto flex shrink-0 items-center gap-1 font-mono text-[11px] text-static">
        {status}
        {onOpen && (
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="transition-transform group-hover:translate-x-0.5"
          />
        )}
      </span>
    </>
  );

  const hasRows = Children.toArray(children).length > 0;

  return (
    <section className="hud overflow-hidden rounded-md">
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          className="group flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-halo/30"
        >
          {heading}
        </button>
      ) : (
        // The same metrics as the button, so the column's rhythm doesn't break
        // on the one card that isn't clickable.
        <div className="flex w-full items-center gap-3 px-4 py-3.5">{heading}</div>
      )}
      {(empty || hasRows) && (
        <div className="border-t border-halo px-4 pb-3 pt-2">
          {/* Both, not either: an empty state can still carry the one link that
              would fix it (the Rig card's route to Config). */}
          {empty && <p className="py-1 text-[12px] leading-relaxed text-static">{empty}</p>}
          {hasRows && <div className="flex flex-col">{children}</div>}
        </div>
      )}
    </section>
  );
}

export function CardRow({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="-mx-1.5 flex items-center gap-2 rounded-sm px-1.5 py-1.5 text-left transition-colors hover:bg-halo/50"
    >
      {children}
    </button>
  );
}

/** A footer line that names a gesture rather than offering a destination. */
export function CardFooterNote({ children }: { children: React.ReactNode }) {
  return (
    <span className="mt-1 self-start font-mono text-[11px] text-static/70">{children}</span>
  );
}

export function CardFooterLink({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group mt-1 flex items-center gap-1 self-start font-mono text-[11px] text-static hover:text-starlight"
    >
      {children}
      <ArrowRight
        size={11}
        strokeWidth={2}
        className="transition-transform group-hover:translate-x-0.5"
      />
    </button>
  );
}
