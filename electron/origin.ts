/**
 * Which URLs are this app's own pages. Everything the shell trusts keys on
 * this: IPC answers only frames showing the app, windows navigate only within
 * it, and a pop-up opens only at one of its routes. Pure, so it is tested.
 *
 * The base is the Vite dev server in development and the `app://` scheme an
 * installed build serves `dist/` from (`window.ts`). Compared by scheme and
 * host rather than `URL.origin`, which is `"null"` for a custom scheme.
 */

export const APP_SCHEME = "app";
export const APP_HOST = "ephymeris";

/** Where the app's pages come from: `EPHYMERIS_DEV_URL` when set (`npm run electron:dev`), else `app://ephymeris/`. */
export function appBase(devUrl: string | undefined): URL {
  return new URL(devUrl ?? `${APP_SCHEME}://${APP_HOST}/`);
}

export function isAppUrl(url: string, base: URL): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  return parsed.protocol === base.protocol && parsed.host === base.host;
}

/**
 * A pop-up's URL (`index.html#/scope/<kind>?…`, from `lib/intan/windows.ts`)
 * resolved against the base, or null unless it is the app's own page at a
 * scope route.
 */
export function scopeUrl(relative: string, base: URL): URL | null {
  let url: URL;
  try {
    url = new URL(relative, base);
  } catch {
    return null;
  }
  const page = url.pathname === base.pathname || url.pathname === `${base.pathname}index.html`;
  return isAppUrl(url.href, base) && page && url.hash.startsWith("#/scope/") ? url : null;
}
