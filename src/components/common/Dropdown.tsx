import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { springSnappy } from "@/lib/motion";

/**
 * A themed listbox — what the native `<select>` could not be.
 *
 * On Windows the native popup is OS chrome: a white panel over a dark app,
 * unstyled options, no way to annotate a row. Every picker on the Task tab
 * went through it, which meant the most-touched control in the editor was the
 * one part of the screen the theme could not reach. This replaces it with an
 * on-theme popover: Nebula surface, Halo hairline, spring entry, and a
 * `detail` slot per option for the second name a row often carries (the wire
 * name behind a rig label, the number behind a strobe code).
 *
 * THE POPOVER IS A PORTAL, positioned from the trigger's rect. The editors
 * live inside scrolling columns, and an absolutely-positioned list would clip
 * at the column edge exactly when it has options enough to matter. Fixed
 * positioning escapes the clip; the price is that the rect goes stale on
 * scroll, so any scroll outside the list closes it rather than letting it
 * drift.
 *
 * FOCUS STAYS ON THE TRIGGER. The list is browsed with the arrow keys via
 * `aria-activedescendant` rather than by moving focus into the portal — one
 * focusable thing, so Tab and blur behave like a `<select>`'s and nothing has
 * to restore focus afterward.
 *
 * A value the options no longer offer still renders, marked missing, in the
 * trigger and at the top of the list. A broken row must show what it is bound
 * to — the diagnostic says the channel is gone; the control must not disagree
 * by reading as unset.
 */
export interface DropdownOption {
  value: string;
  label: string;
  /** Right-aligned mono annotation — a code number, the channel behind a label. */
  detail?: string | undefined;
}

const MAX_LIST_HEIGHT = 244;

export function Dropdown({
  value,
  options,
  placeholder,
  label,
  invalid = false,
  disabled = false,
  attention = false,
  size = "compact",
  className = "",
  onChange,
}: {
  value: string;
  options: DropdownOption[];
  placeholder: string;
  /** Accessible name for the control. */
  label: string;
  /** An external problem with this value — styles the border, nothing else. */
  invalid?: boolean;
  disabled?: boolean;
  /** Same contract as `Select`'s: pulses the border while a guided flow is
   *  waiting on exactly this control. */
  attention?: boolean;
  /** `compact` is the trial table's dense-row size; `regular` matches
   *  `TextInput`/`Select`, for the settings forms. A prop rather than a
   *  `className` override, for `Button.shape`'s reason: two conflicting
   *  padding utilities resolve by stylesheet order, not string order. */
  size?: "compact" | "regular";
  /** Layout-only additions (widths, flex) — visual identity stays here. */
  className?: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const id = useRef(`dd-${Math.random().toString(36).slice(2, 9)}`).current;

  const missing = value !== "" && !options.some((o) => o.value === value);
  const rows: DropdownOption[] = missing
    ? [{ value, label: `${value} (missing)` }, ...options]
    : options;
  const selectedRow = rows.find((o) => o.value === value);

  const show = useCallback(() => {
    const el = triggerRef.current;
    if (!el) return;
    setRect(el.getBoundingClientRect());
    const at = rows.findIndex((o) => o.value === value);
    setActive(at >= 0 ? at : 0);
    setOpen(true);
    // rows/value are read once at open; the list is static while shown.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, options]);

  const close = useCallback(() => setOpen(false), []);

  const commit = useCallback(
    (next: string) => {
      onChange(next);
      setOpen(false);
    },
    [onChange],
  );

  /* Anything that would leave the rect stale ends the popover: a scroll
     outside the list, a resize, a pointer down elsewhere. */
  useEffect(() => {
    if (!open) return;
    const onScroll = (e: Event) => {
      if (listRef.current && e.target instanceof Node && listRef.current.contains(e.target)) return;
      close();
    };
    const onDown = (e: PointerEvent) => {
      if (triggerRef.current?.contains(e.target as Node)) return;
      if (listRef.current?.contains(e.target as Node)) return;
      close();
    };
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", close);
    window.addEventListener("pointerdown", onDown, true);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("pointerdown", onDown, true);
    };
  }, [open, close]);

  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector(`[data-index="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        show();
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(rows.length - 1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const row = rows[active];
      if (row) commit(row.value);
    } else if (e.key === "Escape" || e.key === "Tab") {
      close();
    }
  };

  /* Open upward when the viewport below the trigger cannot hold the list. */
  const dropUp = rect !== null && rect.bottom + MAX_LIST_HEIGHT + 8 > window.innerHeight && rect.top > MAX_LIST_HEIGHT;

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? `${id}-list` : undefined}
        aria-activedescendant={open ? `${id}-opt-${active}` : undefined}
        disabled={disabled}
        onClick={() => (open ? close() : show())}
        onKeyDown={onKeyDown}
        onBlur={close}
        className={`flex min-w-0 items-center justify-between gap-1.5 rounded-sm border text-left transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-40 ${
          size === "regular"
            ? "bg-nebula px-2.5 py-1.5 text-[12px]"
            : "bg-nebula/40 px-2 py-1 text-[11px]"
        } ${
          invalid
            ? "border-status-error text-starlight"
            : open
              ? "border-pulsar text-starlight"
              : `text-starlight hover:border-static/40 focus-visible:border-pulsar ${
                  attention ? "attention-border border-halo" : "border-halo"
                }`
        } ${className}`}
      >
        <span className={`min-w-0 flex-1 truncate ${selectedRow ? "" : "text-static/60"} ${missing ? "text-status-error" : ""}`}>
          {selectedRow?.label ?? placeholder}
        </span>
        <ChevronDown
          size={11}
          strokeWidth={1.75}
          className={`shrink-0 text-static/70 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {createPortal(
        <AnimatePresence>
          {open && rect && (
            <motion.div
              ref={listRef}
              id={`${id}-list`}
              role="listbox"
              aria-label={label}
              initial={{ opacity: 0, y: dropUp ? 4 : -4, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: dropUp ? 4 : -4, scale: 0.98, transition: { duration: 0.1 } }}
              transition={springSnappy}
              style={{
                position: "fixed",
                left: rect.left,
                width: Math.max(rect.width, 176),
                maxHeight: MAX_LIST_HEIGHT,
                ...(dropUp
                  ? { bottom: window.innerHeight - rect.top + 4 }
                  : { top: rect.bottom + 4 }),
              }}
              className="scrollbar-none z-50 overflow-y-auto rounded-md border border-halo bg-nebula py-1 shadow-[0_10px_28px_rgba(0,0,0,0.5)]"
            >
              {rows.length === 0 && (
                <p className="px-2.5 py-2 text-[10px] text-static/60">
                  nothing to offer — check the rig's wiring
                </p>
              )}
              {rows.map((option, index) => {
                const isSelected = option.value === value;
                const isMissing = missing && index === 0;
                return (
                  <button
                    key={option.value || "__empty"}
                    id={`${id}-opt-${index}`}
                    data-index={index}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={-1}
                    // Mousedown, not click: the trigger's blur fires between the
                    // two and would close the list before a click could land.
                    onMouseDown={(e) => {
                      e.preventDefault();
                      commit(option.value);
                    }}
                    onMouseEnter={() => setActive(index)}
                    className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] transition-colors ${
                      index === active ? "bg-halo/50" : ""
                    } ${isMissing ? "text-status-error" : isSelected ? "text-starlight" : "text-static"}`}
                  >
                    <span className="min-w-0 flex-1 truncate">{option.label}</span>
                    {option.detail && (
                      <span className="shrink-0 font-mono text-[9px] text-static/50">
                        {option.detail}
                      </span>
                    )}
                    <span className="w-3 shrink-0">
                      {isSelected && <Check size={11} strokeWidth={2} className="text-pulsar" />}
                    </span>
                  </button>
                );
              })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
