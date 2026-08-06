import { openPath } from "@tauri-apps/plugin-opener";
import { motion } from "framer-motion";
import { Folder, FolderOpen } from "lucide-react";
import { useState } from "react";

import { springSnappy } from "@/lib/motion";

/**
 * Opens a folder the app already knows in the OS file manager — the cohort's
 * data folder from the Analytics header, a session's folder from its summary
 * panel (`data.md` §10.1).
 *
 * Shell-side via the opener plugin, like the dialog and debug-log saves
 * (`settings.md` §4): showing a directory is the OS's job, and nothing about
 * it belongs on the wire. The capability grants `open-path` only — the app
 * never opens URLs.
 *
 * The closed folder opens on hover — the affordance *is* the label. All of it
 * is CSS (`hover:` / `group-hover:`), the same mechanism as every button in
 * `controls.tsx`, so it degrades with them: a rig with no pointer hover simply
 * shows the resting state. Framer carries only the lift, which is decoration.
 * Colour stays within the outline-button vocabulary — border and text
 * brighten, no Pulsar fill, and per §1.2 no glow.
 */
export function FolderButton({
  path,
  label,
  title,
  size = "md",
}: {
  /** Absolute path, handed to the OS verbatim. */
  path: string;
  label: string;
  /** Tooltip; defaults to the path itself, which is the honest answer to
      "which folder?". */
  title?: string;
  /** `sm` sits inside a panel header without inflating its line; the default
      matches the outline buttons in the page's action row. */
  size?: "md" | "sm";
}) {
  const [failed, setFailed] = useState(false);

  async function open() {
    try {
      await openPath(path);
      setFailed(false);
    } catch (err) {
      // An unplugged drive, or no shell bridge (browser preview). The button
      // says so in place — a silent no-op reads as a dead click.
      console.error(`could not open ${path}`, err);
      setFailed(true);
    }
  }

  return (
    <motion.button
      type="button"
      onClick={() => void open()}
      whileHover={{ y: -1 }}
      whileTap={{ y: 0, scale: 0.98 }}
      transition={springSnappy}
      title={title ?? path}
      className={`group flex items-center gap-1.5 rounded-sm border border-halo bg-nebula font-medium text-static transition-colors hover:border-static/70 hover:bg-halo/50 hover:text-starlight ${
        size === "sm" ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-[12px]"
      }`}
    >
      <span aria-hidden className="relative size-[13px]">
        <Folder
          size={13}
          strokeWidth={1.75}
          className="absolute inset-0 transition-opacity duration-150 group-hover:opacity-0"
        />
        <FolderOpen
          size={13}
          strokeWidth={1.75}
          className="absolute inset-0 opacity-0 transition-opacity duration-150 group-hover:opacity-100"
        />
      </span>
      {label}
      {failed && (
        <span
          className="font-normal"
          style={{ color: "var(--color-status-error)" }}
        >
          — couldn&rsquo;t open
        </span>
      )}
    </motion.button>
  );
}
