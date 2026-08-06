import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { springModal } from "@/lib/motion";

/**
 * Transient overlay surface. One of exactly two places vibrancy is permitted
 * (dashboard.md §1.4): persistent chrome (the sidebar) and this. Content
 * cards stay opaque.
 */
/** `md` is the historical width and stays the default, so every existing call
 * site is unchanged; wider sizes exist for content that is a grid rather than
 * a column (the paradigm gallery). */
const WIDTHS = {
  md: "max-w-xl",
  lg: "max-w-3xl",
  xl: "max-w-5xl",
} as const;

export function Modal({
  open,
  onClose,
  title,
  size = "md",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  size?: keyof typeof WIDTHS;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Portalled to `body`, and that is load-bearing rather than tidiness: `fixed`
  // is only viewport-relative while nothing above it is a containing block, and
  // `.surface` — every content card in the app — carries `backdrop-filter`,
  // which makes one. In place, this overlay sized and centred itself to
  // whichever card it happened to be declared inside (the cohort editor's
  // Change-data-folder dialog came out 958×182px, pinned inside the Cohort
  // group). `.vibrancy` and `.hud` do the same, so does any framer transform
  // mid-animation, and a call site cannot see which of those it sits under.
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-8">
          <motion.div
            className="absolute inset-0 bg-void/70"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            className={`vibrancy relative flex max-h-full w-full flex-col rounded-lg border border-halo shadow-xl ${WIDTHS[size]}`}
            initial={{ opacity: 0, scale: 0.96, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={springModal}
          >
            <header className="flex items-center justify-between border-b border-halo px-5 py-3.5">
              <h2 className="font-display text-[15px] font-semibold text-starlight">{title}</h2>
              <button
                type="button"
                aria-label="Close dialog"
                onClick={onClose}
                className="text-static transition-colors hover:text-starlight"
              >
                <X size={16} strokeWidth={1.75} />
              </button>
            </header>
            <div className="min-h-0 overflow-y-auto p-5">{children}</div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
