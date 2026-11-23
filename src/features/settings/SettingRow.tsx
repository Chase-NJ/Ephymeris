import { createContext, useContext, type ReactNode } from "react";

import { InfoHint } from "@/components/common/InfoHint";

/**
 * How much room a `SettingRow` spends on its explanation — set by the surface,
 * read by the row.
 *
 * `"full"` prints the description under the label: the settings screens and
 * the Record step, where a row is read once, carefully. `"compact"` keeps it
 * behind an `InfoHint` and tightens the row, for a display that has to fit on
 * one screen (the Recording tab). A context rather than a prop for the reason
 * `rowDensity.ts` gives: the row groups between surface and row
 * (`RecordingConfigRows`) need no changes.
 */
export type SettingRowDensity = "full" | "compact";

export const SettingRowDensityContext = createContext<SettingRowDensity>("full");

export function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  const density = useContext(SettingRowDensityContext);
  if (density === "compact") {
    return (
      // The label never truncates — it is short, and the only thing naming the
      // control. A wide control wraps under it instead.
      <div className="flex min-h-[44px] flex-wrap items-center justify-between gap-x-4 gap-y-1.5 border-b border-halo/70 px-4 py-1.5 last:border-b-0">
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-[13px] font-medium whitespace-nowrap text-starlight">{label}</span>
          {description && <InfoHint label={`About ${label}`}>{description}</InfoHint>}
        </div>
        <div className="ml-auto">{children}</div>
      </div>
    );
  }
  return (
    <div className="flex items-start justify-between gap-8 border-b border-halo px-4 py-3.5 last:border-b-0">
      <div className="min-w-0 pt-0.5">
        <div className="text-[13px] font-medium text-starlight">{label}</div>
        {description && (
          <p className="mt-0.5 text-[12px] leading-relaxed text-static">{description}</p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export function SettingGroup({
  title,
  children,
  variant = "surface",
}: {
  title: string;
  children: ReactNode;
  /**
   * `"surface"` is opaque Nebula, for the in-flow settings screens.
   *
   * `"hud"` is the frosted variant, for a group floating over the live 3D sky —
   * the guided session steps. An opaque card there punches a hole in the
   * constellation behind it; `.hud` is 55% Nebula over a 20px backdrop blur, so
   * the sky reads through the glass. Same distinction `BoxCard` and `StarPanel`
   * make.
   */
  variant?: "surface" | "hud";
}) {
  return (
    <section className="mt-7">
      <h2 className="mb-2 px-1 font-display text-[13px] font-medium tracking-wide text-static uppercase">
        {title}
      </h2>
      <div className={`${variant} rounded-md`}>{children}</div>
    </section>
  );
}
