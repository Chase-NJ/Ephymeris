/**
 * Stage everything the installer bundles beyond the app itself.
 *
 * Produces `src-tauri/resources/` (gitignored, regenerated on every run):
 *
 *   resources/
 *     sidecar/                PyInstaller-frozen sidecar (onedir)
 *       ephymeris-sidecar.exe
 *       _internal/ephymeris_sidecar/rig/
 *         schema/ hardware/              the channel, pinout and strobe registries
 *     arduino/
 *       arduino-cli.exe       copied from this machine's PATH
 *       data/                 a clean `arduino:avr` install (core + avr-gcc +
 *                             avrdude) seeded via `core install` into an empty
 *                             directory, so nothing from the dev machine's own
 *                             Arduino15 rides along
 *     sketches/               the bundled sketch library, freshly staged by
 *                             stage-sketches.mjs from firmware/
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

// PyInstaller freezes whatever `import ephymeris_sidecar` resolves to in this
// venv, which is not necessarily the tree beside it. A NON-editable install left
// over from an earlier `pip install .` shadows the source from every directory
// except `sidecar/` itself, and the freeze would take the stale copy without a
// word — an installer built from source that does not match the source. Ask the
// interpreter where the package actually is rather than assuming.
let resolved;
try {
  resolved = execFileSync(
    python,
    ["-c", "import ephymeris_sidecar as m, ephymeris_sidecar.rig.registry; print(m.__file__)"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], cwd: repoRoot },
  ).trim();
} catch {
  console.error(
    "\nthe venv cannot import ephymeris_sidecar.rig (see above).\n" +
      `  ${python} -m pip install -e "${sidecarDir}[dev,package]"`,
  );
  process.exit(1);
}
if (resolve(dirname(resolved)) !== resolve(join(sidecarDir, "ephymeris_sidecar"))) {
  console.error(
    `the venv's ephymeris_sidecar is ${resolved}\n` +
      `but this repo's is ${join(sidecarDir, "ephymeris_sidecar")}.\n` +
      "Freezing would bundle the wrong one. Reinstall editable:\n" +
      `  ${python} -m pip install -e "${sidecarDir}[dev,package]"`,
  );
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

run(python, [
  "-m", "PyInstaller",
  "--noconfirm", "--clean", "--onedir", "--console",
  "--name", "ephymeris-sidecar",
  "--collect-submodules", "ephymeris_sidecar",
  // rig/schema and rig/hardware — package data the import analysis never sees,
  // and without which the sidecar starts and then cannot name a single pin or
  // strobe. `_log_rig_wiring()` prints the composed wiring at startup, which is
  // what turns a missing one into a startup failure rather than a first-use one
  // on a lab machine.
  "--collect-data", "ephymeris_sidecar",
  "--add-data", rpcData("cc"),
  "--add-data", rpcData("google"),
  // `jsonschema` needs --collect-all rather than plain analysis because
  // `jsonschema_specifications` ships its metaschemas as package DATA, and the
  // import analysis brings the code without them.
  "--collect-all", "jsonschema",
  "--collect-all", "jsonschema_specifications",
  // The generated arduino-cli stubs are shipped as data (above), so the one
  // place `google.protobuf` is imported from is invisible to the analysis —
  // `boards/rpc/__init__.py` explicitly expects it from the installed wheel and
  // vendors only `google.rpc`. Without this the frozen sidecar starts, reports
  // `grpcio unavailable (No module named 'google.protobuf')` and runs the whole
  // lab on the subprocess backend. The fallback is doing its job there, which is
  // exactly why the hole was quiet: nothing breaks, flashing just loses live
  // compiler streaming on every packaged build.
  "--collect-all", "google.protobuf",
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

// --- 4. bundle the sketch library ------------------------------------------
// Sketches ship with the app (`TASKS.md#sketch-library`). stage-sketches.mjs owns the
// merge of the two source repos; this just re-runs it fresh and copies the
// result into the installer payload. Never reuses a stale staging, unlike the
// arduino data seed — sketches are small and edited often, and a stale copy in
// an installer is exactly the drift bundling exists to end.

run(process.execPath, [join(repoRoot, "scripts", "stage-sketches.mjs")]);
const sketchesOut = join(resourcesDir, "sketches");
rmSync(sketchesOut, { recursive: true, force: true });
cpSync(join(repoRoot, "sketches"), sketchesOut, { recursive: true });
console.log(`staged sketch library (${sizeOf(sketchesOut)})`);

console.log(`\nresources staged at ${resourcesDir} — total ${sizeOf(resourcesDir)}`);
