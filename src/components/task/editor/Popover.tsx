import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/**
 * A panel set in front of the page from a header button (`.hud-front`).
 *
 * Controlled, so the editor can open Details itself on a new task. Escape or a
 * pointer-down outside closes it, and focus returns to the trigger — the one
 * place the keyboard was before it opened.
 */
export function Popover({
  open,
  onOpenChange,
  trigger,
  label,
  width = 340,
  align = "right",
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The trigger's contents; it renders as the button. */
  trigger: ReactNode;
  /** Accessible name of the panel. */
  label: string;
  width?: number;
  align?: "left" | "right";
  children: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) onOpenChange(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      onOpenChange(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onOpenChange]);

  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => onOpenChange(!open)}
        className={`flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-[11px] transition-colors ${
          open
            ? "border-pulsar/60 bg-pulsar/10 text-starlight"
            : "border-halo bg-nebula/60 text-static hover:border-static/60 hover:text-starlight"
        }`}
      >
        {trigger}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            id={id}
            role="dialog"
            aria-label={label}
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={springSnappy}
            style={{ width, originY: 0 }}
            className={`hud-front absolute top-full z-40 mt-2 rounded-md p-4 ${
              align === "right" ? "right-0" : "left-0"
            }`}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
