import type { SpecTableSummary } from "@/lib/specs/types";

/**
 * The last star: what the walk produced, and the one remaining decision.
 *
 * The id error is suppressed WHILE CREATING, because the save lands in the
 * library before the route changes — so the id this screen is about becomes
 * "taken" by its own success and flashes as an error on the way out.
 */
export function ReviewStep({
  table,
  idError,
  creating,
}: {
  table: SpecTableSummary | null | undefined;
  idError: string | null;
  creating: boolean;
}) {
  return (
    <p className="text-[11.5px] leading-relaxed text-static">
      {table
        ? `${table.nNodes} states, ${table.nEdges} edges, ${table.sizeBytes} bytes.`
        : "The spec has to compile before it can be created."}
      {!creating && idError && (
        <span className="mt-1 block" style={{ color: "var(--color-status-error)" }}>
          {idError}
        </span>
      )}
    </p>
  );
}
