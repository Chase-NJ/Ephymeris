/**
 * Development flags for the Task tab (`TASKS.md#the-spine-editor`).
 *
 * The phase-spine editor is under development and has not run on a real box,
 * so `+ New task` opens the trial-table editor. The spine's seed chooser stays
 * reachable behind this flag, set by hand in the webview's devtools:
 *
 *     localStorage.setItem("ephymeris:spineEditor", "1")
 *
 * A saved spine task still opens in its own editor whatever the flag says: the
 * flag gates making a new one, never reading one that exists.
 */

const SPINE_EDITOR_KEY = "ephymeris:spineEditor";

export function spineEditorEnabled(): boolean {
  try {
    return window.localStorage.getItem(SPINE_EDITOR_KEY) === "1";
  } catch {
    return false;
  }
}
