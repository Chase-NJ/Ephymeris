import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { springModal } from "@/lib/motion";

/**
 * Transient overlay surface. One of exactly two places vibrancy is permitted
 * (dashboard.md §1.4): persistent chrome (the sidebar) and this. Content
 * cards stay opaque.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
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

  return (
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
            className="vibrancy relative flex max-h-full w-full max-w-xl flex-col rounded-lg border border-halo shadow-xl"
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
    </AnimatePresence>
  );
}
