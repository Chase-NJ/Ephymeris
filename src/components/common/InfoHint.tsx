import { AnimatePresence, motion } from "framer-motion";
import { Info } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/**
 * A row's explanation, kept one hover away (`SettingRow`'s compact density).
 *
 * The explanation is still there for whoever needs it and still reachable
 * without a mouse — focus opens it exactly as hover does, Escape closes it —
 * but a page of settings no longer pays a paragraph per row to carry it.
 */
export function InfoHint({ children, label = "More about this" }: { children: ReactNode; label?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="relative inline-flex"
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        className="flex size-4 items-center justify-center rounded-full text-static/60 transition-colors hover:text-starlight focus:outline-none focus-visible:text-starlight focus-visible:ring-1 focus-visible:ring-pulsar"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
      >
        <Info size={12} strokeWidth={1.75} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.span
            id={id}
            role="tooltip"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={springSnappy}
            className="hud-front pointer-events-none absolute top-full left-1/2 z-30 mt-2 w-max max-w-[280px] bg-nebula/95 -translate-x-1/2 rounded-sm px-3 py-2 text-left text-[12px] leading-relaxed font-normal text-static"
            style={{ originY: 0 }}
          >
            {children}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
