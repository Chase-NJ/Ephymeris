import type { ReactNode } from "react";

/**
 * A titled, bordered block that explains itself — a list of problems, a set of
 * things an action would break, a refusal and its reason.
 *
 * `tone="warning"` borders it in the state colour, which is the only thing the
 * colour may mean (`ARCHITECTURE.md#theme`): something here needs a decision.
 * `tone="error"` is a refusal the operator cannot pass. Neither is decoration.
 */
export function Callout({
  title,
  why,
  tone,
  children,
}: {
  title: string;
  why?: ReactNode;
  tone?: "warning" | "error";
  children?: ReactNode;
}) {
  const border =
    tone === "warning"
      ? "var(--color-status-warning)"
      : tone === "error"
        ? "var(--color-status-error)"
        : "var(--color-halo)";
  return (
    <div
      className="flex flex-col gap-1.5 rounded-sm border px-2.5 py-2"
      style={{ borderColor: border }}
    >
      <div className="font-mono text-[10px] tracking-wider text-static uppercase">{title}</div>
      {why && <p className="text-[10.5px] leading-relaxed text-static">{why}</p>}
      {children}
    </div>
  );
}
