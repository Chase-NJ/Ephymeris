import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { springPanel } from "@/lib/motion";

/**
 * Shared stub for the three unwired sections (dashboard.md §2).
 *
 * The point of this component is that clicking a nav item should still feel
 * like the app responded — an honest "not yet" rather than a dead button. It
 * takes a title, a short line in the interface's own voice, and optionally a
 * disabled preview of what the real view will contain.
 */
export function PlaceholderView({
  title,
  icon: Icon,
  children,
  preview,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
  preview?: ReactNode;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto flex min-h-full max-w-3xl flex-col justify-center px-10 py-12"
    >
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
          <Icon size={18} strokeWidth={1.75} className="text-pulsar" />
        </span>
        <h1 className="font-display text-xl text-starlight">{title}</h1>
      </div>

      <p className="mt-4 max-w-prose text-[13px] leading-relaxed text-static">{children}</p>

      {preview && (
        <div
          className="mt-8 select-none opacity-35 grayscale"
          aria-hidden
          inert
        >
          {preview}
        </div>
      )}
    </motion.section>
  );
}
