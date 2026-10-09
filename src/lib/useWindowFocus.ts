import { useEffect, useState } from "react";

/**
 * Whether the app's window has focus. Ambient motion — the 2D `Starfield` and
 * the 3D sky's drift — holds while it doesn't, because this app is watched
 * during live data collection and ambient effects must never compete for
 * attention (`ARCHITECTURE.md#theme`).
 *
 * Starts `true`: the window opens focused, and a sky that began paused until
 * the first focus event would look broken.
 */
export function useWindowFocus(): boolean {
  const [focused, setFocused] = useState(true);

  useEffect(() => {
    const onFocus = () => setFocused(true);
    const onBlur = () => setFocused(false);
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  return focused;
}
