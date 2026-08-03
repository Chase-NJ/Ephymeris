import { TextInput, Toggle } from "@/components/common/controls";

/**
 * One labelled value row: label + help + changed-dot on the left, the input and
 * unit suffix on the right. Extracted from `ConfigFields`' leaf so the task
 * profile form and the spec editor share the invariants that matter —
 * clamp-never-reject on numbers, and the mid-typing escape hatch that keeps a
 * half-typed value visible instead of silently substituting a default.
 *
 * Deliberately data-only: no `ConfigField`, no `TaskProfile`, no spec types.
 * The two forms serve different document shapes (a flat `config[]` vs a nested
 * spec) and must not converge above this leaf — but a number field behaving
 * differently between them would be a bug someone pays for at 8am, so the leaf
 * is one component.
 */
export type FieldRowType = "int" | "float" | "bool" | "string";

export function FieldRow({
  label,
  help,
  unit,
  type,
  value,
  fallback,
  baseline,
  min,
  max,
  error,
  mono = true,
  width,
  onChange,
}: {
  label: string;
  help?: string | undefined;
  unit?: string | undefined;
  type: FieldRowType;
  value: unknown;
  /** What an emptied input reverts to — the profile/spec default. */
  fallback: unknown;
  /** What "unchanged" means here; drives the changed-dot. */
  baseline: unknown;
  min?: number | undefined;
  max?: number | undefined;
  /**
   * A compiler/validator message for THIS field, rendered in the same slot and
   * tone as the not-a-number message. The row stays editable — an error is
   * something to fix, not a lock. (Disabling rides the enclosing fieldset, as
   * both forms already do.)
   */
  error?: string | undefined;
  mono?: boolean;
  /** Layout-only override for the input width class. */
  width?: string | undefined;
  onChange: (next: unknown) => void;
}) {
  // A number the user is mid-typing ("-", "0.") isn't a number yet, so it is
  // held as text and reported rather than silently swallowed. The old form
  // stored the raw string in `config`, and the START builder then quietly
  // substituted the profile default — the operator saw their value on screen
  // and the board ran on a different one.
  const numeric = type === "int" || type === "float";
  const invalid = numeric && typeof value === "string" && value.trim() !== "";
  const changed = !Object.is(value, baseline);

  return (
    <label className="flex items-start justify-between gap-3">
      <span className="min-w-0 pt-1">
        <span
          className={`block truncate text-[11px] ${changed ? "text-starlight" : "text-static"}`}
          title={help ?? label}
        >
          {changed && <span className="mr-1 text-pulsar">•</span>}
          {label}
        </span>
        {help && (
          <span className="mt-0.5 block text-[10px] leading-snug text-static/70">
            {help}
          </span>
        )}
        {invalid && (
          <span
            className="mt-0.5 block text-[10px]"
            style={{ color: "var(--color-status-error)" }}
          >
            Not a number — the box would run on {String(fallback)}.
          </span>
        )}
        {error && !invalid && (
          <span
            className="mt-0.5 block text-[10px] leading-snug"
            style={{ color: "var(--color-status-error)" }}
          >
            {error}
          </span>
        )}
      </span>

      <span className="flex shrink-0 items-center gap-1.5">
        {type === "bool" ? (
          <Toggle
            label={label}
            checked={value === true}
            onChange={onChange}
          />
        ) : numeric ? (
          <TextInput
            label={label}
            mono={mono}
            value={String(value ?? "")}
            onChange={(raw) => {
              if (raw.trim() === "") return onChange(fallback);
              const parsed = type === "int" ? parseInt(raw, 10) : parseFloat(raw);
              // Keep the raw text on a partial entry so the caret doesn't jump;
              // `invalid` above is what makes that state visible.
              onChange(Number.isNaN(parsed) ? raw : clamp(parsed, min, max));
            }}
            className={width ?? "w-[76px]"}
          />
        ) : (
          <TextInput
            label={label}
            mono={mono && type !== "string"}
            value={String(value ?? "")}
            onChange={onChange}
            className={width ?? "w-[120px]"}
          />
        )}
        <span className="w-6 shrink-0 font-mono text-[10px] text-static/70">
          {unit ?? ""}
        </span>
      </span>
    </label>
  );
}

/**
 * Clamp a parsed number into the field's declared range.
 *
 * Clamping rather than rejecting: these bounds exist to keep a typo from
 * reaching the firmware (a zero polling rate is a hang, a bias window past the
 * ring buffer is an overrun), and silently refusing a keystroke mid-edit is
 * worse than landing on the nearest legal value.
 */
function clamp(value: number, min?: number, max?: number): number {
  if (min !== undefined && value < min) return min;
  if (max !== undefined && value > max) return max;
  return value;
}
