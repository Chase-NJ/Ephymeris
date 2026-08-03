/**
 * Stage everything the installer bundles beyond the app itself.
 *
 * Produces `src-tauri/resources/` (gitignored, regenerated on every run):
 *
 *   resources/
 *     sidecar/                PyInstaller-frozen sidecar (onedir)
 *       ephymeris-sidecar.exe
 *       _internal/...
 *         vendor/             the vendored Task-Graph compiler, as plain .py on
 *                             disk — it is imported off sys.path, not from the
 *                             archive (see the --add-data note below)
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
 *
 * The `bundle.resources` mapping for these lives in
 * `src-tauri/tauri.bundle.conf.json`, merged in only by `npm run package`'s
 * `tauri build --config` — keeping it out of `tauri.conf.json` means
 * `tauri dev` works on machines that have never staged resources.
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

// The vendored arduino-cli gRPC stubs (`boards/rpc/cc`, `boards/rpc/google`)
// are imported via a sys.path entry that `boards/rpc/__init__.py` appends, so
// PyInstaller's import analysis cannot see them — ship them as data files;
// the frozen app's path finder imports plain .py from sys.path just fine.
const sep = win ? ";" : ":";
const rpcData = (sub) => {
  const rel = join("ephymeris_sidecar", "boards", "rpc", sub);
  // Source must be absolute: PyInstaller resolves a relative source against
  // `--specpath` (build/), not the cwd the freeze runs in. The destination
  // stays relative — that half really is app-bundle-relative.
  return `${join(sidecarDir, rel)}${sep}${rel}`;
};

// The vendored Task-Graph compiler ships the same way and for the same reason:
// `specs/_vendor.py` puts `sidecar/vendor/` on sys.path at runtime, so the
// analysis cannot see it either. It has to stay plain .py on disk rather than
// go into the archive, because `templates.load()` imports a module whose name it
// computes and `templates.source_hash()` reads the file's own bytes — neither
// works against a frozen module.
//
// The excludes are not belt-and-braces. If `taskgraph` ever happens to be
// pip-installed in the freezing venv, the analysis would find it and bake a
// SECOND copy into the archive alongside the one on sys.path — and the linter's
// rule registry and the lru_cached registries are module-level state, so two
// copies disagree silently. Excluding it makes the sys.path copy the only one
// that can ever win.
const vendorData = `${join(sidecarDir, "vendor")}${sep}vendor`;

run(python, [
  "-m", "PyInstaller",
  "--noconfirm", "--clean", "--onedir", "--console",
  "--name", "ephymeris-sidecar",
  "--collect-submodules", "ephymeris_sidecar",
  "--add-data", rpcData("cc"),
  "--add-data", rpcData("google"),
  "--add-data", vendorData,
  "--exclude-module", "taskgraph",
  "--exclude-module", "templates",
  // The vendor tree's OWN dependencies, declared by hand for the same reason the
  // tree is shipped as data: nothing PyInstaller analyses imports them. `yaml`
  // and `jsonschema` are imported only from vendor/taskgraph/, which the analysis
  // treats as opaque bytes, so without these the frozen sidecar bundles the
  // compiler and then cannot import it. `jsonschema` needs --collect-all rather
  // than --hidden-import because `jsonschema_specifications` ships its metaschemas
  // as package DATA, and a hidden-import brings the code without them.
  "--hidden-import", "yaml",
  "--collect-all", "jsonschema",
  "--collect-all", "jsonschema_specifications",
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
