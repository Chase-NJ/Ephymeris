import { Select, TextInput, Toggle } from "@/components/common/controls";
import type { ConfigField, TaskProfile } from "@/lib/sessions/types";

/**
 * Per-box pre-flight config form (`starting-a-session.md` §3).
 *
 * Fields, labels and defaults come straight from the sketch's Task Profile
 * `config` array (`data-saving.md` §6.2) — the app knows nothing task-specific.
 * A sketch with no profile renders nothing at all, and gets a bare `START`.
 */
export function TaskConfigForm({
  profile,
  config,
  onChange,
}: {
  profile: TaskProfile | null;
  config: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  if (!profile || profile.config.length === 0) return null;

  function set(key: string, value: unknown) {
    onChange({ ...config, [key]: value });
  }

  return (
    <div className="mt-2 flex flex-col gap-1.5 border-t border-halo pt-2">
      <div className="font-mono text-[10px] text-static">{profile.taskName}</div>
      {profile.config.map((field) => (
        <Field
          key={field.metadataKey}
          field={field}
          value={config[field.metadataKey] ?? field.default}
          onChange={(v) => set(field.metadataKey, v)}
        />
      ))}
    </div>
  );
}

function Field({
  field,
  value,
  onChange,
}: {
  field: ConfigField;
  value: unknown;
  onChange: (next: unknown) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="min-w-0 truncate text-[11px] text-static" title={field.label}>
        {field.label}
      </span>
      {field.type === "bool" ? (
        <Toggle label={field.label} checked={value === true} onChange={onChange} />
      ) : field.type === "int" || field.type === "float" ? (
        <TextInput
          label={field.label}
          mono
          value={String(value ?? "")}
          onChange={(v) => {
            const parsed = field.type === "int" ? parseInt(v, 10) : parseFloat(v);
            onChange(v.trim() === "" ? field.default : Number.isNaN(parsed) ? v : parsed);
          }}
          className="w-[76px]"
        />
      ) : (
        <TextInput
          label={field.label}
          value={String(value ?? "")}
          onChange={onChange}
          className="w-[120px]"
        />
      )}
    </label>
  );
}

/** Sketch picker scoped to one box, grouped by category (§3). */
export function SketchPicker({
  sketches,
  value,
  onChange,
  label,
  className = "",
}: {
  sketches: Array<{ category: string; name: string; path: string }>;
  value: string | null;
  onChange: (path: string | null) => void;
  label: string;
  /** Layout-only — forwarded to the underlying Select. */
  className?: string;
}) {
  const options = [
    { value: "", label: "— select a sketch —" },
    ...sketches.map((s) => ({ value: s.path, label: `${s.category} / ${s.name}` })),
  ];
  return (
    <Select
      label={label}
      value={value ?? ""}
      options={options}
      onChange={(v) => onChange(v === "" ? null : String(v))}
      // The flow is waiting on exactly this control until a sketch is picked.
      attention={value === null}
      className={className}
    />
  );
}
