/**
 * Stage everything the installer bundles beyond the app itself.
 *
 * Produces `build/resources/` (gitignored, regenerated on every run), which the
 * installer packages from (`extraResources` in `electron-builder.yml`):
 *
 *   resources/
 *     sidecar/                PyInstaller-frozen sidecar (onedir), started
 *                             once here and made to do real work
 *       ephymeris-sidecar[.exe]
 *       _internal/ephymeris_sidecar/rig/
 *         schema/ hardware/              the channel, pinout and strobe registries
 *     arduino/
 *       arduino-cli[.exe]     copied from this machine's PATH
 *       data/                 a clean `arduino:avr` install (core + avr-gcc +
 *                             avrdude) seeded via `core install` into an empty
 *                             directory, so nothing from the dev machine's own
 *                             Arduino15 rides along
 *     tasksim/                the task simulator: the trial runner compiled for
 *                             this machine, one executable per selection mode
 *     sketches/               the bundled sketch library: firmware/, copied
 *                             without dotfiles or host-test build output
 *
 * The shell resolves these through its resource directory and hands their
 * locations to the sidecar via EPHYMERIS_BUNDLED_* env vars; the sidecar
 * copies `data/` to a writable location on first use (`boards/cli_tool.py`).
 *
 * Run via `npm run package:electron` (which chains `electron-builder`), or
 * standalone with `node scripts/package-resources.mjs`.
 */

import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, rmSync, statSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sidecarDir = join(repoRoot, "sidecar");
const resourcesDir = join(repoRoot, "build", "resources");
const win = process.platform === "win32";
const exe = win ? ".exe" : "";

// Packaging is proven on Windows x64 (the lab PCs) and Apple silicon macOS.
// Everything staged here is this machine's own architecture: the freeze, the
// arduino-cli on PATH and the avr toolchain `core install` downloads.
if (!win && !(process.platform === "darwin" && process.arch === "arm64")) {
  console.warn(`warning: packaging is unproven on ${process.platform}/${process.arch}; continuing anyway`);
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
  // Every submodule of the sidecar but its tests, which live inside each
  // feature's package (`packaging/hooks/hook-ephymeris_sidecar.py`). Absolute,
  // for the reason `rpcData` gives.
  "--additional-hooks-dir", join(sidecarDir, "packaging", "hooks"),
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
// Links copied as written: a macOS freeze holds relative ones (Python.framework's
// `Versions/Current`), and cpSync otherwise rewrites each into an absolute path
// back into this checkout, which codesign refuses and no other Mac could follow.
cpSync(frozen, join(resourcesDir, "sidecar"), { recursive: true, verbatimSymlinks: true });
console.log(`\nstaged sidecar (${sizeOf(join(resourcesDir, "sidecar"))})`);

// The staged copy is started as the shell starts it and made to recover a
// crashed run, whose `.mat` is read back (`sidecar/packaging/check_frozen.py`).
// A freeze that hangs at launch, or starts and cannot write a `.mat`, stops
// the packaging here rather than reaching a lab machine.
run(python, [join("packaging", "check_frozen.py"), join(resourcesDir, "sidecar", `ephymeris-sidecar${exe}`)], {
  cwd: sidecarDir,
});

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
// The binary itself: Homebrew's `arduino-cli` on PATH is a link into its Cellar.
rmSync(join(arduinoDir, `arduino-cli${exe}`), { force: true });
copyFileSync(cliPath, join(arduinoDir, `arduino-cli${exe}`));
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
// Sketches ship with the app (`TASKS.md#sketch-library`), copied fresh from
// `firmware/` on every run — never a stale copy, unlike the arduino data seed:
// sketches are small and edited often, and a stale copy in an installer is
// exactly the drift bundling exists to end. A dev run needs no copy at all;
// the sidecar reads `firmware/` in place (`discovery.library_root()`).

const firmwareDir = join(repoRoot, "firmware");
const sketchesOut = join(resourcesDir, "sketches");
rmSync(sketchesOut, { recursive: true, force: true });
cpSync(firmwareDir, sketchesOut, {
  recursive: true,
  // Symlinks resolved, not copied: the lab machines are Windows, where a
  // symlink in an installer payload is a support call.
  dereference: true,
  filter: (src) => {
    const parts = src.slice(firmwareDir.length).split(/[\\/]/).filter(Boolean);
    // Dotfiles (.gitignore, .DS_Store) are repo plumbing, and the host tests'
    // compiled binaries are this machine's build output.
    if (parts.some((part) => part.startsWith("."))) return false;
    const name = parts.at(-1) ?? "";
    return !(parts.includes("host_test") && /^(test|test_box)(\.exe|\.obj)?$/.test(name));
  },
});
const inos = readdirSync(sketchesOut, { withFileTypes: true, recursive: true }).filter(
  (e) => e.isFile() && e.name.endsWith(".ino"),
).length;
if (inos === 0) {
  console.error(`no sketches found in ${firmwareDir}`);
  process.exit(1);
}
console.log(`bundled sketch library: ${inos} sketches (${sizeOf(sketchesOut)})`);

// --- 5. build the task simulator --------------------------------------------
// The firmware's own trial runner, compiled for this machine and run through one
// trial before it is staged (`TASKS.md#simulating-a-task`). Needs a C++ compiler
// on PATH: MinGW's g++ on Windows, linked statically, clang or gcc elsewhere.
// A failure stops the packaging: an installer without it would offer a Simulate
// view that can only refuse.

const tasksimOut = join(resourcesDir, "tasksim");
rmSync(tasksimOut, { recursive: true, force: true });
mkdirSync(tasksimOut, { recursive: true });
run(
  python,
  ["-m", "ephymeris_sidecar.simulation", "--out", tasksimOut, "--firmware", firmwareDir],
  { cwd: sidecarDir },
);

console.log(`\nresources staged at ${resourcesDir} — total ${sizeOf(resourcesDir)}`);
