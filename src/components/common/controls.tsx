import { motion } from "framer-motion";
import { useRef, useState, type ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/** Shared form primitives, so every control gets the theme tokens and radii. */

export function Button({
  children,
  onClick,
  variant = "secondary",
  shape = "text",
  disabled = false,
  title,
  label,
  className = "",
}: {
  children: ReactNode;
  onClick: () => void;
  /**
   * `outline` carries a visible border — for icon-only controls that would
   * otherwise read as decoration rather than something to click.
   */
  variant?: "primary" | "secondary" | "ghost" | "outline";
  /**
   * Picks the padding/sizing set. A prop rather than a `className` override
   * because two conflicting utilities for the same property (`px-3` vs `px-0`)
   * are resolved by stylesheet order, not by the order they appear in the
   * class string — which silently squashed this button's icon to 2px wide.
   */
  shape?: "text" | "icon";
  disabled?: boolean;
  title?: string;
  /** Accessible name. Needed when the button's content is only an icon. */
  label?: string;
  /**
   * Layout-only additions (widths, alignment, wrapping) — visual identity
   * stays here, exactly as on `Select` and `TextInput`. Do **not** pass
   * padding or colour utilities: two conflicting utilities for one property
   * are resolved by stylesheet order, not by string order, which is the trap
   * `shape` exists to avoid.
   */
  className?: string;
}) {
  const styles = {
    primary: "bg-pulsar text-void hover:brightness-108",
    secondary: "bg-halo/60 text-starlight hover:bg-halo",
    ghost: "text-static hover:text-starlight",
    // Matches the border/fill of TextInput and Select so it reads as part of
    // the same row rather than floating loose at the end of it.
    outline:
      "border border-halo bg-nebula text-static hover:border-static/70 hover:bg-halo/50 hover:text-starlight",
  }[variant];

  const sizing =
    shape === "icon" ? "size-7 shrink-0 justify-center" : "px-3 py-1.5";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={label ?? title}
      className={`flex items-center gap-1.5 rounded-sm text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`flex h-[22px] w-[38px] items-center rounded-xl p-[3px] transition-colors ${
        checked ? "bg-pulsar" : "bg-halo"
      }`}
    >
      <motion.span
        layout
        transition={springSnappy}
        className="block size-4 rounded-xl bg-starlight"
        style={{ marginLeft: checked ? "auto" : 0 }}
      />
    </button>
  );
}

/**
 * A segmented control — a handful of mutually exclusive views behind one
 * strip of buttons. The selector for things a `Select` would hide: every
 * option stays visible, and switching is one click, not two.
 */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (next: T) => void;
  /** Accessible name for the group. */
  label: string;
}) {
  return (
    <span
      role="group"
      aria-label={label}
      // Wraps rather than overflowing: the condition picker carries the
      // operator's own names, and six of them do not fit a chart header. The
      // divider is per-button so a wrapped row still reads as one control.
      className="flex flex-wrap overflow-hidden rounded-sm border border-halo"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          className={`px-2.5 py-1 text-[11px] transition-colors ${
            value === option.value
              ? "bg-halo/70 text-starlight"
              : "text-static hover:text-starlight"
          }`}
        >
          {option.label}
        </button>
      ))}
    </span>
  );
}

export function Select<T extends string | number>({
  value,
  options,
  onChange,
  label,
  disabled = false,
  attention = false,
  tone = "normal",
  className = "",
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (next: T) => void;
  label: string;
  disabled?: boolean;
  /** Pulses the border until the user acts — for the one control a guided
      flow is waiting on. */
  attention?: boolean;
  /**
   * Tints the selected value when the *current* choice is the problem — a box
   * whose board is gone, say. Colour lands on the text only; the
   * border stays Halo like every other control so a warning row doesn't read
   * as a different kind of surface.
   */
  tone?: "normal" | "warning" | "error";
  /** Layout-only additions (widths, flex) — visual identity stays here. */
  className?: string;
}) {
  const toned =
    tone === "warning"
      ? { color: "var(--color-status-warning)" }
      : tone === "error"
        ? { color: "var(--color-status-error)" }
        : undefined;
  return (
    <select
      aria-label={label}
      value={String(value)}
      disabled={disabled}
      {...(toned ? { style: toned } : {})}
      onChange={(e) => {
        const next = options.find((o) => String(o.value) === e.target.value);
        if (next) onChange(next.value);
      }}
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 font-mono text-[12px] ${
        tone === "normal" ? "text-starlight" : ""
      } disabled:cursor-not-allowed disabled:opacity-40 ${
        attention ? "attention-border" : ""
      } ${className}`}
    >
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/**
 * The one numeric entry control — every tunable number in the app types through
 * this.
 *
 * IT HOLDS A DRAFT WHILE FOCUSED, and that is the whole design. Three separate
 * inputs used to parse and commit on every keystroke, which made the field
 * uneditable in three compounding ways:
 *
 *  - **Backspace could not clear it.** An emptied input committed immediately —
 *    to the default here, to `0` in the ramp table — so the character came back
 *    as fast as it was deleted and the only way to change a value was to append
 *    to it.
 *  - **Clamping fought the typist.** `min` applied per keystroke, so on a field
 *    floored at 100 the first digit of "250" snapped to 100 and the rest landed
 *    on the end of it. The operator got 1002 and no indication why.
 *  - **Decimals could not be typed.** `parseFloat("5.")` is 5, which re-rendered
 *    as "5" and ate the point; the next digit made 55 rather than 5.5.
 *
 * The draft is raw text, so a half-typed value stays exactly as typed. What
 * parses is reported up **live and unclamped** — the preview, the state machine
 * and the diagnostics keep following along — and blur is what COMMITS: clamped
 * into range, or back to `fallback` if what is on screen is not a number. So the
 * transient disagreement lasts exactly as long as the caret is in the box, and
 * a field left holding nonsense visibly snaps to the value the box would run on
 * rather than quietly disagreeing with it.
 *
 * FOCUS SELECTS THE WHOLE ENTRY, so typing replaces the line rather than
 * inserting into it — the ordinary way to retune a number is to click it and
 * type the new one.
 *
 * `type="text"` rather than `type="number"`: a number input refuses to display
 * text it cannot parse, so it blanks itself on "1." or "-" and takes the draft
 * with it. It also treats a stray scroll over a focused field as an edit.
 */
export function NumberInput({
  value,
  fallback,
  integer = false,
  min,
  max,
  label,
  title,
  mono = true,
  align = "left",
  invalid = false,
  autoFocus = false,
  className = "",
  onChange,
}: {
  /** The committed value. Tolerates a non-number so a legacy stored string still renders. */
  value: unknown;
  /** What an emptied or unreadable entry commits to on blur. */
  fallback: unknown;
  /** Truncate to a whole number on commit. */
  integer?: boolean;
  min?: number | undefined;
  max?: number | undefined;
  label: string;
  title?: string | undefined;
  mono?: boolean;
  align?: "left" | "right";
  /** An external problem with this value — styles the border, nothing else. */
  invalid?: boolean;
  /** For a row the user just created and is about to fill — the ramp's new
   *  stage. Focus selects the seeded value, so typing replaces it outright. */
  autoFocus?: boolean;
  /** Layout-only additions (widths) — visual identity stays here. */
  className?: string;
  onChange: (next: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  // Clicking into a field fires focus (where the selection is made) and then
  // mouseup, which collapses it to a caret. Swallowing that one mouseup is what
  // makes click-then-type replace the entry.
  const selecting = useRef(false);

  const text = draft ?? String(value ?? "");

  function read(raw: string): number | null {
    const trimmed = raw.trim();
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) return null;
    return integer ? Math.trunc(parsed) : parsed;
  }

  // "-", "1." and "." are on the way to a number, not a failure — flagging them
  // would put a red border under every negative and every decimal mid-entry.
  const partial =
    draft !== null && (draft.trim() === "" || /^-?(\d*\.?\d*)$/.test(draft.trim()));
  const unreadable = draft !== null && !partial && read(draft) === null;

  return (
    <input
      type="text"
      inputMode={integer ? "numeric" : "decimal"}
      aria-label={label}
      title={title}
      value={text}
      // eslint-disable-next-line jsx-a11y/no-autofocus -- the cell of a row
      // the user just added; focus belongs there and nowhere else.
      autoFocus={autoFocus}
      onFocus={(e) => {
        setDraft(String(value ?? ""));
        selecting.current = true;
        e.currentTarget.select();
      }}
      onMouseUp={(e) => {
        if (!selecting.current) return;
        selecting.current = false;
        e.preventDefault();
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        const parsed = read(raw);
        // Unclamped on purpose: clamping here is what turns "250" into 1002 on
        // a floored field. The commit below is where range is enforced.
        if (parsed !== null) onChange(parsed);
      }}
      onBlur={() => {
        const parsed = draft === null ? null : read(draft);
        setDraft(null);
        selecting.current = false;
        onChange(parsed === null ? (read(String(fallback)) ?? 0) : clampTo(parsed, min, max));
      }}
      onKeyDown={(e) => {
        // Enter commits without leaving the field, Escape abandons the draft —
        // both are what a spreadsheet-shaped table of numbers implies.
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "Escape") {
          setDraft(null);
          e.currentTarget.blur();
        }
      }}
      className={`rounded-sm border bg-nebula px-2.5 py-1.5 text-[12px] text-starlight transition-colors focus:outline-none ${
        mono ? "font-mono" : ""
      } ${align === "right" ? "text-right" : ""} ${
        invalid || unreadable
          ? "border-status-error"
          : "border-halo hover:border-static/40 focus:border-pulsar"
      } ${className}`}
    />
  );
}

/**
 * Clamp a committed number into a field's declared range.
 *
 * Clamping rather than rejecting: these bounds exist to keep a typo from
 * reaching the firmware (a zero polling rate is a hang, a bias window past the
 * ring buffer is an overrun), and refusing the entry outright would leave the
 * operator with no way to find out what the legal value was.
 */
export function clampTo(value: number, min?: number, max?: number): number {
  if (min !== undefined && value < min) return min;
  if (max !== undefined && value > max) return max;
  return value;
}

export function TextInput({
  value,
  onChange,
  onSubmit,
  placeholder,
  label,
  mono = false,
  autoFocus = false,
  attention = false,
  className = "",
}: {
  value: string;
  onChange: (next: string) => void;
  /** Enter commits. For a field whose whole job is "type this, then go". */
  onSubmit?: () => void;
  placeholder?: string;
  label: string;
  mono?: boolean;
  autoFocus?: boolean;
  /** Same contract as `Select`'s: the one control a guided flow is waiting on. */
  attention?: boolean;
  className?: string;
}) {
  return (
    <input
      type="text"
      aria-label={label}
      value={value}
      placeholder={placeholder}
      // eslint-disable-next-line jsx-a11y/no-autofocus -- the first field of a
      // guided create flow; focus belongs there and nowhere else.
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
      {...(onSubmit
        ? {
            onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onSubmit();
              }
            },
          }
        : {})}
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] text-starlight transition-colors placeholder:text-static/60 hover:border-static/40 focus:border-pulsar focus:outline-none ${
        mono ? "font-mono" : ""
      } ${attention ? "attention-border" : ""} ${className}`}
    />
  );
}
