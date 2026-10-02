import { useReducedMotion } from "framer-motion";

import { useSettings } from "./settings/context";

/**
 * Combines the OS `prefers-reduced-motion` signal with the app's own toggle
 * (`ARCHITECTURE.md#theme`).
 *
 * The system preference is always honoured; the setting can only add to it,
 * never override it back on. Someone who has asked their OS for reduced motion
 * should not have to ask this app separately.
 */
export function useReduceMotion(): boolean {
  const systemPreference = useReducedMotion();
  const { settings } = useSettings();
  return Boolean(systemPreference) || settings.reducedMotion;
}
