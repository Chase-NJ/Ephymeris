/**
 * Stage the bundled sketch library into `<repo>/sketches/`.
 *
 * Sketches ship WITH the app now — there is no user-configured Arduino
 * Directory (`docs/tasks.md` §2). This script is what makes "ship with the app"
 * true, and it runs in two places: `npm run predev`, so a dev build has a
 * library without staging installer resources, and `scripts/package-resources.mjs`,
 * which copies the result into `src-tauri/resources/sketches`.
 *
 * Two source repos, one destination, because the app needs both and
 * `arduino-cli compile` takes exactly one `--libraries` root:
 *
 *   ../Arduino      the lab's behaviour sketches + libraries/BehaviorBox
 *   ../Task-Graph   Arduino/TaskRunner_* + libraries/TaskInterpreter
 *
 * The two `libraries/` collections are MERGED into the single staged root. That
 * is the whole reason this script exists rather than a `cpSync` call: Task-Graph's
 * own `Arduino/build.sh` passes two library roots, Ephymeris passes one, and
 * merging is what lets an interpreter sketch compile through the existing
 * `port.flash` path with no special case anywhere.
 *
 * `sketches/` is gitignored and regenerated. It is a build output, not a mirror —
 * nobody edits it, and committing it would create a copy of the firmware repo
 * inside this one that would drift the first time someone touched a sketch.
 *
 * Sources are overridable so a machine with a different layout can still build:
 *   EPHYMERIS_FIRMWARE_REPO   default ../Arduino
 *   EPHYMERIS_TASKGRAPH_REPO  default ../Task-Graph
 */

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stagedDir = join(repoRoot, "sketches");

const firmwareRepo = resolve(
  process.env.EPHYMERIS_FIRMWARE_REPO ?? join(repoRoot, "..", "Arduino"),
);
const taskGraphRepo = resolve(
  process.env.EPHYMERIS_TASKGRAPH_REPO ?? join(repoRoot, "..", "Task-Graph"),
);

/**
 * Where Task-Graph's interpreter sketches are filed.
 *
 * They need a category folder like any other sketch — discovery reports a sketch
 * sitting at the root as skipped, because it has nothing to be filed under. The
 * name is doing real work: `Task-Graph/Arduino/README.md` says "nothing in this
 * folder is for animal use", and a box carrying one of these accepts a table and
 * reports whether it fits. It runs no trial and delivers no reward.
 */
const BENCH_CATEGORY = "Bench";

const IGNORE_PREFIXES = [".", "_"];

function isCategoryCandidate(name) {
  return !IGNORE_PREFIXES.some((p) => name.startsWith(p)) && name.toLowerCase() !== "libraries";
}

function copyTree(from, to, what) {
  if (!existsSync(from)) return false;
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, {
    recursive: true,
    // Symlinks are resolved rather than copied: the lab machines are Windows,
    // where a symlink in an installer payload is a support call.
    dereference: true,
    // Discovery ignores dotted folders silently, so one riding along would be
    // invisible rather than harmful — but it would still be in the installer,
    // and `.git` inside a source repo would be tens of megabytes of it.
    filter: (src) => !src.split(/[\\/]/).some((part) => part.startsWith(".") && part.length > 1),
  });
  console.log(`  ${what}`);
  return true;
}

function countSketches(dir) {
  let n = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true, recursive: true })) {
    if (entry.isFile() && entry.name.endsWith(".ino")) {
      // The folder-name-matches-.ino rule discovery applies; count what will
      // actually be offered rather than what merely exists.
      const folder = entry.parentPath.split(/[\\/]/).pop();
      if (entry.name === `${folder}.ino`) n += 1;
    }
  }
  return n;
}

function requireRepo(path, name, envVar) {
  if (!existsSync(path)) {
    console.error(
      `${name} not found at ${path}\n` +
        `Sketches ship with the app, so this repo is required to build one.\n` +
        `Set ${envVar} if yours lives elsewhere.`,
    );
    process.exit(1);
  }
}

requireRepo(firmwareRepo, "the firmware repo", "EPHYMERIS_FIRMWARE_REPO");
requireRepo(taskGraphRepo, "the Task-Graph repo", "EPHYMERIS_TASKGRAPH_REPO");

console.log(`staging sketch library into ${stagedDir}`);
rmSync(stagedDir, { recursive: true, force: true });
mkdirSync(stagedDir, { recursive: true });

// --- 1. the lab's behaviour sketches ---------------------------------------
// Every top-level folder except `libraries/` is a category, and their names are
// not hardcoded anywhere — "Utility" and "Olfactory Behavior" are what this lab
// happens to have, not an enum.
for (const entry of readdirSync(firmwareRepo, { withFileTypes: true })) {
  if (!entry.isDirectory() || !isCategoryCandidate(entry.name)) continue;
  copyTree(join(firmwareRepo, entry.name), join(stagedDir, entry.name), entry.name);
}

// --- 2. Task-Graph's interpreter sketches ----------------------------------
const tgArduino = join(taskGraphRepo, "Arduino");
for (const entry of readdirSync(tgArduino, { withFileTypes: true })) {
  if (!entry.isDirectory() || !isCategoryCandidate(entry.name)) continue;
  if (!existsSync(join(tgArduino, entry.name, `${entry.name}.ino`))) continue;
  copyTree(
    join(tgArduino, entry.name),
    join(stagedDir, BENCH_CATEGORY, entry.name),
    `${BENCH_CATEGORY}/${entry.name}`,
  );
}

// --- 3. merge both library collections into one root -----------------------
// Only the root `libraries/` reaches `arduino-cli --libraries`, so every sketch
// compiles against one predictable collection regardless of which repo it came
// from.
const librariesDir = join(stagedDir, "libraries");
mkdirSync(librariesDir, { recursive: true });

for (const [source, label] of [
  [join(firmwareRepo, "libraries"), "libraries (firmware)"],
  [join(tgArduino, "libraries"), "libraries (Task-Graph)"],
]) {
  if (!existsSync(source)) continue;
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    const target = join(librariesDir, entry.name);
    if (existsSync(target)) {
      console.error(
        `library name collision: ${entry.name} exists in both collections.\n` +
          "Both would be handed to one --libraries root, so one would silently " +
          "shadow the other. Rename one before continuing.",
      );
      process.exit(1);
    }
    copyTree(join(source, entry.name), target, `${label}/${entry.name}`);
  }
}

const total = countSketches(stagedDir);
const bytes = readdirSync(stagedDir, { withFileTypes: true, recursive: true })
  .filter((e) => e.isFile())
  .reduce((sum, e) => sum + statSync(join(e.parentPath, e.name)).size, 0);

console.log(`\n${total} sketches, ${Math.round(bytes / 1024)} KB`);

if (total === 0) {
  console.error("no valid sketches staged — check the source repos");
  process.exit(1);
}
