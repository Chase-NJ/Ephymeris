import { NumberInput, TextInput, Toggle } from "@/components/common/controls";
import { useRowDensity } from "@/components/common/rowDensity";

/**
 * One labelled value row: label + help + changed-dot on the left, the input and
 * unit suffix on the right. Its invariants are the ones every value form must
 * share — clamp-never-reject on numbers, and the mid-typing escape hatch that
 * keeps a half-typed value visible instead of silently substituting a default.
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
  // A number the user is mid-typing ("-", "0.") isn't a number yet. `NumberInput`
  // holds that as a draft and commits on blur, so `config` carries a number
  // whenever the caret is elsewhere — which is what keeps the old failure from
  // returning: the raw string used to be stored, and the START builder then
  // quietly substituted the profile default, so the operator saw their value on
  // screen and the board ran on a different one.
  //
  // The message below therefore only fires on a value that arrived already
  // broken — a hand-edited profile, or one written before the draft existed.
  // It stays because a stored string is exactly the case that must not go quiet.
  const numeric = type === "int" || type === "float";
  const invalid = numeric && typeof value === "string" && value.trim() !== "";
  const changed = !Object.is(value, baseline);
  const stacked = useRowDensity() === "stacked";

  const caption = (
    <>
      <span
        className={`block text-[11px] ${stacked ? "" : "truncate"} ${
          changed ? "text-starlight" : "text-static"
        }`}
        title={help ?? label}
      >
        {changed && <span className="mr-1 text-pulsar">•</span>}
        {label}
      </span>
      {help && (
        <span className="mt-0.5 block text-[10px] leading-snug text-static/70">{help}</span>
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
    </>
  );

  // A stacked row gives the control the full column; the inline one keeps the
  // fixed widths the two forms were laid out around.
  const control =
    type === "bool" ? (
      <Toggle label={label} checked={value === true} onChange={onChange} />
    ) : numeric ? (
      <NumberInput
        label={label}
        mono={mono}
        value={value}
        fallback={fallback}
        integer={type === "int"}
        min={min}
        max={max}
        className={stacked ? "w-full" : (width ?? "w-[76px]")}
        onChange={onChange}
      />
    ) : (
      <TextInput
        label={label}
        mono={mono && type !== "string"}
        value={String(value ?? "")}
        onChange={onChange}
        className={stacked ? "w-full" : (width ?? "w-[120px]")}
      />
    );

  if (stacked) {
    return (
      <label className="flex min-w-0 flex-col gap-1">
        <span className="min-w-0">{caption}</span>
        <span className="flex min-w-0 items-center gap-1.5">
          {control}
          {unit && (
            <span className="shrink-0 font-mono text-[10px] text-static/70">{unit}</span>
          )}
        </span>
      </label>
    );
  }

  return (
    <label className="flex items-start justify-between gap-3">
      <span className="min-w-0 pt-1">{caption}</span>
      <span className="flex shrink-0 items-center gap-1.5">
        {control}
        <span className="w-6 shrink-0 font-mono text-[10px] text-static/70">
          {unit ?? ""}
        </span>
      </span>
    </label>
  );
}
