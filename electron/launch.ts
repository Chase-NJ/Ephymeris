/**
 * How the sidecar is launched (`ARCHITECTURE.md#which-sidecar-runs`): either the
 * repo's venv interpreter running the package, or the PyInstaller-frozen
 * executable bundled with an installed app.
 *
 * Pure: every fact about the machine comes in through `LaunchContext`, so the
 * ordering is tested without a filesystem or an Electron app.
 */

import { join } from "node:path";

export interface Launch {
  program: string;
  /** `["-m", "ephymeris_sidecar"]` for an interpreter, empty for the frozen exe. */
  args: string[];
  cwd: string;
}

export interface LaunchContext {
  /** `EPHYMERIS_SIDECAR_PYTHON`, when set. */
  explicitPython: string | undefined;
  /** An installed build (`app.isPackaged`) rather than a run from the checkout. */
  packaged: boolean;
  /** The checkout, which holds `sidecar/.venv` in development. */
  repoRoot: string;
  /** Where an installed build's bundled resources live (`process.resourcesPath`). */
  resourcesPath: string;
  windows: boolean;
  isFile(path: string): boolean;
  isDirectory(path: string): boolean;
}

/** The repo's `sidecar/.venv` interpreter: the development path. */
export function venvLaunch(ctx: LaunchContext): Launch {
  const venv = join(ctx.repoRoot, "sidecar", ".venv");
  return {
    program: ctx.windows ? join(venv, "Scripts", "python.exe") : join(venv, "bin", "python"),
    args: ["-m", "ephymeris_sidecar"],
    cwd: join(ctx.repoRoot, "sidecar"),
  };
}

/** The frozen sidecar staged by `scripts/package-resources.mjs`, if this build carries one. */
export function frozenLaunch(ctx: LaunchContext): Launch | null {
  const dir = join(ctx.resourcesPath, "sidecar");
  const exe = join(dir, ctx.windows ? "ephymeris-sidecar.exe" : "ephymeris-sidecar");
  return ctx.isFile(exe) ? { program: exe, args: [], cwd: dir } : null;
}

/**
 * `EPHYMERIS_SIDECAR_PYTHON` always wins, for running against a bespoke
 * interpreter. After that the two builds prefer opposite orders on purpose: a
 * run from the checkout wants the live venv (edit Python, relaunch, see it), an
 * installed build wants the frozen exe it shipped with. Each falls back to the
 * other.
 */
export function resolveLaunch(ctx: LaunchContext): Launch {
  const venv = venvLaunch(ctx);
  if (ctx.explicitPython) return { ...venv, program: ctx.explicitPython };

  const venvIfPresent = ctx.isFile(venv.program) ? venv : null;
  const frozen = frozenLaunch(ctx);
  const launch = ctx.packaged ? (frozen ?? venvIfPresent) : (venvIfPresent ?? frozen);
  if (launch) return launch;
  throw new Error(
    "No sidecar found: neither a bundled ephymeris-sidecar executable nor a sidecar/.venv " +
      "interpreter. For development, create the venv (see README); for packaging, run `npm run package`.",
  );
}

/**
 * The bundled arduino-cli, its data seed and the sketch library, exported to
 * the sidecar as environment variables. Present only when the resources exist
 * (an installed build), so a dev sidecar keeps resolving `arduino-cli` from
 * PATH and reads `<repo>/firmware` in place (`discovery.library_root()`).
 */
export function bundledEnv(ctx: LaunchContext): Record<string, string> {
  const env: Record<string, string> = {};
  const arduino = join(ctx.resourcesPath, "arduino");
  const cli = join(arduino, ctx.windows ? "arduino-cli.exe" : "arduino-cli");
  const seed = join(arduino, "data");
  const sketches = join(ctx.resourcesPath, "sketches");
  if (ctx.isFile(cli)) env["EPHYMERIS_BUNDLED_ARDUINO_CLI"] = cli;
  if (ctx.isDirectory(seed)) env["EPHYMERIS_BUNDLED_ARDUINO_DATA_SEED"] = seed;
  if (ctx.isDirectory(sketches)) env["EPHYMERIS_BUNDLED_SKETCHES"] = sketches;
  return env;
}
