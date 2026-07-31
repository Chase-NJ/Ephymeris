import type { ReactNode } from "react";

export function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
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
   * make (`index.css` §2.4).
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
