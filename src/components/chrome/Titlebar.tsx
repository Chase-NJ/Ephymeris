import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Minus, Square, X } from "lucide-react";

/**
 * App-drawn titlebar (dashboard.md §2.1, §5).
 *
 * Native decorations are off on both platforms — macOS does not keep its
 * traffic lights — so the chrome is identical on the dev machine and the lab
 * PCs. The bar itself is the drag region; the controls opt out of it.
 */

/**
 * Resolved lazily rather than at module scope: touching the Tauri bridge during
 * import would throw anywhere the shell isn't present (browser preview, tests)
 * and take the whole render tree down with it.
 */
function appWindow() {
  return getCurrentWindow();
}

export function Titlebar() {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    let active = true;
    let unlisten: (() => void) | undefined;

    try {
      const win = appWindow();
      const sync = () => void win.isMaximized().then((v) => active && setMaximized(v));
      sync();
      void win.onResized(sync).then((fn) => {
        if (active) unlisten = fn;
        else fn();
      });
    } catch {
      // No shell bridge; the controls simply won't do anything.
    }

    return () => {
      active = false;
      unlisten?.();
    };
  }, []);

  return (
    <header
      data-tauri-drag-region
      className="flex h-9 shrink-0 items-center justify-between border-b border-halo bg-void/80 pl-3"
    >
      <div data-tauri-drag-region className="pointer-events-none flex items-center gap-2">
        <AppMark />
        <span className="font-display text-[13px] font-semibold tracking-tight text-starlight">
          Ephymeris
        </span>
      </div>

      <div className="flex h-full items-stretch">
        <ControlButton label="Minimize" onClick={() => void appWindow().minimize()}>
          <Minus size={14} strokeWidth={1.5} />
        </ControlButton>
        <ControlButton
          label={maximized ? "Restore" : "Maximize"}
          onClick={() => void appWindow().toggleMaximize()}
        >
          <Square size={11} strokeWidth={1.5} />
        </ControlButton>
        <ControlButton label="Close" onClick={() => void appWindow().close()} danger>
          <X size={15} strokeWidth={1.5} />
        </ControlButton>
      </div>
    </header>
  );
}

/**
 * The app mark — the one place the squircle is spent (§2.4). A six-point star
 * on a Pulsar field: the constellation motif at icon scale. Deliberately NOT
 * the bundle icon (`src-tauri/icons/icon.svg`, the rat-on-a-rocket): at 17px
 * that artwork is an unreadable smudge, and this star was built for this size.
 */
function AppMark() {
  return (
    <span className="squircle block size-[17px] bg-pulsar" aria-hidden>
      <svg viewBox="0 0 40 40" className="size-full">
        <path
          d="M20 7 L22.6 17.4 L33 20 L22.6 22.6 L20 33 L17.4 22.6 L7 20 L17.4 17.4 Z"
          fill="var(--color-void)"
        />
      </svg>
    </span>
  );
}

function ControlButton({
  children,
  label,
  onClick,
  danger = false,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={`flex w-11 items-center justify-center text-static transition-colors hover:text-starlight ${
        danger ? "hover:bg-status-error" : "hover:bg-halo"
      }`}
    >
      {children}
    </button>
  );
}
