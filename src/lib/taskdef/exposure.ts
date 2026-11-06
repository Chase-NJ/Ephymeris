/**
 * Which of a task's parameters are exposed (`TASKS.md#parameters`).
 *
 * A task's parameters all start at their defaults and out of sight. The
 * operator exposes the ones they mean to tune; only those appear in the
 * editor's Parameters panel and in the Start dialog, and the list rides the
 * definition (`exposed`) into the generated profile. Everything hidden is
 * still sent on the `SET` lines at its default: exposure changes what is
 * shown, never what reaches the board.
 *
 * Pure: the panel and the Start dialog both read these, so they cannot
 * disagree about what "exposed" means.
 */

import { isRowOwnedField } from "./lines";
import type { ConfigField, TaskProfile } from "@/lib/ws/protocol";
import { orderGroups } from "@/lib/tasks/topology";

/** One row of the picker: a field, whether it is exposed, and its two values. */
export interface PickerEntry {
  field: ConfigField;
  exposed: boolean;
  /** What the task compiles with today. */
  value: unknown;
  /** The catalogue's default, what a reset returns to. */
  defaultValue: unknown;
  /** The task pins a value other than the default. */
  pinned: boolean;
}

export interface PickerGroup {
  group: string;
  entries: PickerEntry[];
}

/** The fields a task can expose: everything the profile declares except what
 *  lives on a trial row (`isRowOwnedField`). */
export function exposableFields(profile: TaskProfile | null): ConfigField[] {
  return (profile?.config ?? []).filter((f) => !isRowOwnedField(f.metadataKey));
}

/** The exposed fields, in the profile's own order; keys the profile no longer
 *  declares are dropped rather than shown as blanks. */
export function exposedFields(profile: TaskProfile | null, exposed: readonly string[]): ConfigField[] {
  const wanted = new Set(exposed);
  return exposableFields(profile).filter((f) => wanted.has(f.metadataKey));
}

/** Group names with at least one exposed field, in trial order. */
export function exposedGroups(profile: TaskProfile | null, exposed: readonly string[]): string[] {
  return orderGroups(new Set(exposedFields(profile, exposed).map((f) => f.group ?? "")));
}

/**
 * The picker's rows, grouped by the profile's `group` in trial order and
 * narrowed by `query` against the label, the key, the group and the unit,
 * case-insensitively. A blank query lists everything.
 */
export function pickerGroups(
  profile: TaskProfile | null,
  exposed: readonly string[],
  config: Record<string, unknown>,
  baseline: Record<string, unknown>,
  query = "",
): PickerGroup[] {
  const shown = new Set(exposed);
  const needle = query.trim().toLowerCase();
  const byGroup = new Map<string, PickerEntry[]>();
  for (const field of exposableFields(profile)) {
    const group = field.group ?? "";
    const haystack = `${field.label} ${field.metadataKey} ${group} ${field.unit ?? ""} ${field.help ?? ""}`.toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    const value = config[field.metadataKey] ?? field.default;
    const defaultValue = baseline[field.metadataKey] ?? field.default;
    const entry: PickerEntry = {
      field,
      exposed: shown.has(field.metadataKey),
      value,
      defaultValue,
      pinned: !Object.is(value, defaultValue),
    };
    const list = byGroup.get(group);
    if (list) list.push(entry);
    else byGroup.set(group, [entry]);
  }
  return orderGroups(byGroup.keys()).map((group) => ({ group, entries: byGroup.get(group) ?? [] }));
}

/** `exposed` with `key` added, in profile order so the panel's order is stable. */
export function expose(profile: TaskProfile | null, exposed: readonly string[], key: string): string[] {
  if (exposed.includes(key)) return [...exposed];
  const next = new Set([...exposed, key]);
  const order = exposableFields(profile).map((f) => f.metadataKey);
  return order.filter((k) => next.has(k)).concat([...next].filter((k) => !order.includes(k)));
}

/**
 * Hide `key` and return its value to the default: what the picker's one-click
 * "reset & hide" does. The config comes back with the key dropped, which is
 * how the editor says "no override" (`TaskEditor.onParams` skips undefined).
 */
export function hideAndReset(
  exposed: readonly string[],
  config: Record<string, unknown>,
  key: string,
): { exposed: string[]; config: Record<string, unknown> } {
  const next = { ...config };
  delete next[key];
  return { exposed: exposed.filter((k) => k !== key), config: next };
}

/** How the Start dialog reads a profile: the keys it offers, or null for a
 *  profile that declares no `exposed` (a hand-written one), which offers all. */
export function offeredKeys(profile: TaskProfile): Set<string> | null {
  return profile.exposed ? new Set(profile.exposed) : null;
}

/** Render a value the way the picker shows it: a number with its unit, a
 *  flag as on/off, text as is. */
export function showValue(field: ConfigField, value: unknown): string {
  if (field.type === "bool") return value ? "on" : "off";
  if (value === undefined || value === null) return "—";
  const text = typeof value === "number" ? String(value) : String(value);
  return field.unit ? `${text} ${field.unit}` : text;
}
