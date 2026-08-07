import { useLayoutEffect, useRef, useState, type RefObject } from "react";

/**
 * The rendered content-box width of one element, live across resizes.
 *
 * For drawings that lay themselves out in CSS pixels rather than letting a
 * viewBox scale them (`SketchStateMachine`): the component needs the number,
 * not just a `w-full`. Returns `null` until the first measurement lands, so a
 * caller can tell "not yet measured" from a genuinely zero-width host.
 *
 * Rounded to whole pixels — sub-pixel churn from the observer would re-render
 * a layout that cannot show the difference.
 */
export function useElementWidth<T extends HTMLElement>(): [
  RefObject<T | null>,
  number | null,
] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState<number | null>(null);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width;
      if (measured !== undefined) {
        setWidth((previous) => {
          const next = Math.round(measured);
          return previous === next ? previous : next;
        });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}
