/**
 * Stage everything the installer bundles beyond the app itself.
 *
 * Produces `src-tauri/resources/` (gitignored, regenerated on every run):
 *
 *   resources/
 *     sidecar/                PyInstaller-frozen sidecar (onedir)
 *       ephymeris-sidecar.exe
 *       _internal/...
 *     arduino/
 *       arduino-cli.exe       copied from this machine's PATH
 *       data/                 a clean `arduino:avr` install (core + avr-gcc +
 *                             avrdude) seeded via `core install` into an empty
 *                             directory, so nothing from the dev machine's own
 *                             Arduino15 rides along
 *
 * The shell resolves these through Tauri's resource dir and hands their
 * locations to the sidecar via EPHYMERIS_BUNDLED_* env vars; the sidecar
 * copies `data/` to a writable location on first use (`boards/cli_tool.py`).
 *
 * Run via `npm run package` (which chains `tauri build` after this), or
 * standalone with `node scripts/package-resources.mjs`.
 */

import { execFileSync, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, rmSync, statSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sidecarDir = join(repoRoot, "sidecar");
const resourcesDir = join(repoRoot, "src-tauri", "resources");
const win = process.platform === "win32";
const exe = win ? ".exe" : "";

// Packaging has only been exercised on Windows — the lab targets. The macOS
// path would need a mac arduino-cli and a mac PyInstaller run; nothing here is
// Windows-specific by design, but don't pretend it's been proven.
if (!win) {
  console.warn("warning: packaging has only been verified on Windows; continuing anyway");
}

function run(cmd, args, opts = {}) {
  console.log(`\n> ${cmd} ${args.join(" ")}`);
  const result = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (result.status !== 0) {
    console.error(`${cmd} exited ${result.status}`);
    process.exit(1);
  }
}

function sizeOf(dir) {
  let total = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    if (entry.isFile()) total += statSync(join(entry.parentPath, entry.name)).size;
  }
  return `${Math.round(total / 1024 / 1024)} MB`;
}

// --- 1. freeze the sidecar -------------------------------------------------

const python = join(sidecarDir, ".venv", win ? "Scripts" : "bin", `python${exe}`);
if (!existsSync(python)) {
  console.error(`sidecar venv not found at ${python} — create it first (see README)`);
  process.exit(1);
}

run(python, [
  "-m", "PyInstaller",
  "--noconfirm", "--clean", "--onedir", "--console",
  "--name", "ephymeris-sidecar",
  "--collect-submodules", "ephymeris_sidecar",
  "--distpath", "dist",
  "--workpath", "build",
  "--specpath", "build",
  join("packaging", "entry.py"),
], { cwd: sidecarDir });

const frozen = join(sidecarDir, "dist", "ephymeris-sidecar");
rmSync(join(resourcesDir, "sidecar"), { recursive: true, force: true });
mkdirSync(resourcesDir, { recursive: true });
cpSync(frozen, join(resourcesDir, "sidecar"), { recursive: true });
console.log(`\nstaged sidecar (${sizeOf(join(resourcesDir, "sidecar"))})`);

// --- 2. bundle arduino-cli -------------------------------------------------

let cliPath;
try {
  const found = execFileSync(win ? "where" : "which", ["arduino-cli"], { encoding: "utf8" });
  cliPath = found.split(/\r?\n/).find(Boolean);
} catch {
  console.error("arduino-cli not found on PATH — install it before packaging");
  process.exit(1);
}

const arduinoDir = join(resourcesDir, "arduino");
mkdirSync(arduinoDir, { recursive: true });
cpSync(cliPath, join(arduinoDir, `arduino-cli${exe}`));
console.log(`staged arduino-cli from ${cliPath}`);

// --- 3. seed the arduino:avr core -----------------------------------------
// `core install` needs the network; the seed survives between runs, so only a
// deleted resources/ pays that cost again.

const dataDir = join(arduinoDir, "data");
if (existsSync(join(dataDir, "packages", "arduino"))) {
  console.log(`arduino data seed already present (${sizeOf(dataDir)}) — skipping core install`);
} else {
  rmSync(dataDir, { recursive: true, force: true });
  mkdirSync(dataDir, { recursive: true });
  const env = {
    ...process.env,
    ARDUINO_DIRECTORIES_DATA: dataDir,
    ARDUINO_DIRECTORIES_DOWNLOADS: join(dataDir, "staging"),
  };
  run(join(arduinoDir, `arduino-cli${exe}`), ["core", "update-index"], { env });
  run(join(arduinoDir, `arduino-cli${exe}`), ["core", "install", "arduino:avr"], { env });
  // The downloaded archives are dead weight once extracted.
  rmSync(join(dataDir, "staging"), { recursive: true, force: true });
  console.log(`seeded arduino:avr (${sizeOf(dataDir)})`);
}

console.log(`\nresources staged at ${resourcesDir} — total ${sizeOf(resourcesDir)}`);
