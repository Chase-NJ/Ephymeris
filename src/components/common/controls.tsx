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
      className={`flex items-center gap-1.5 rounded-sm text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${sizing} ${styles}`}
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

export function Select<T extends string | number>({
  value,
  options,
  onChange,
  label,
  disabled = false,
  attention = false,
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
  /** Layout-only additions (widths, flex) — visual identity stays here. */
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={String(value)}
      disabled={disabled}
      onChange={(e) => {
        const next = options.find((o) => String(o.value) === e.target.value);
        if (next) onChange(next.value);
      }}
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 font-mono text-[12px] text-starlight disabled:cursor-not-allowed disabled:opacity-40 ${
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
  placeholder,
  label,
  mono = false,
  className = "",
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  label: string;
  mono?: boolean;
  className?: string;
}) {
  return (
    <input
      type="text"
      aria-label={label}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded-sm border border-halo bg-nebula px-2.5 py-1.5 text-[12px] text-starlight placeholder:text-static/60 ${
        mono ? "font-mono" : ""
      } ${className}`}
    />
  );
}
