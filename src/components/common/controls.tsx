import { motion } from "framer-motion";
import type { ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/** Shared form primitives, so every control picks up the §2 tokens and radii. */

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
      className="flex overflow-hidden rounded-sm border border-halo"
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
   * whose board is gone, say. Colour lands on the text only, per §2.2; the
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
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] text-starlight placeholder:text-static/60 ${
        mono ? "font-mono" : ""
      } ${attention ? "attention-border" : ""} ${className}`}
    />
  );
}
