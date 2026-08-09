/**
 * Stage the bundled sketch library into `<repo>/sketches/`.
 *
 * Sketches ship WITH the app — there is no user-configured Arduino Directory
 * (`docs/tasks.md` §2). This script is what makes "ship with the app" true, and
 * it runs in two places: `npm run predev`, so a dev build has a library without
 * staging installer resources, and `scripts/package-resources.mjs`, which copies
 * the result into `src-tauri/resources/sketches`.
 *
 * One source:
 *
 *   ../Arduino        the lab's behaviour sketches + libraries/BehaviorBox
 *
 * It used to be two. `<repo>/firmware` held the task-spec interpreter library
 * and its bench sketch, and this script existed largely to MERGE the two
 * `libraries/` collections into one root, because `arduino-cli compile` takes
 * exactly one `--libraries` path. That system was removed; the merge went with
 * it, and what remains is a filtered copy that still has to be a script rather
 * than a `cpSync` call for two reasons: `.git` inside a source repo would put
 * tens of megabytes into the installer, and symlinks have to be resolved rather
 * than copied because the lab machines are Windows.
 *
 * `sketches/` is gitignored and regenerated. It is a build output, not a mirror —
 * nobody edits it, and committing it would create a copy of the firmware repo
 * inside this one that would drift the first time someone touched a sketch.
 *
 * The behaviour-sketch source is overridable so a machine with a different
 * layout can still build:
 *   EPHYMERIS_FIRMWARE_REPO   default ../Arduino
 */

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const stagedDir = join(repoRoot, "sketches");

const behaviorRepo = resolve(
  process.env.EPHYMERIS_FIRMWARE_REPO ?? join(repoRoot, "..", "Arduino"),
);

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

if (!existsSync(behaviorRepo)) {
  console.error(
    `the behaviour firmware repo not found at ${behaviorRepo}\n` +
      "Sketches ship with the app, so this repo is required to build one.\n" +
      "Set EPHYMERIS_FIRMWARE_REPO if yours lives elsewhere.",
  );
  process.exit(1);
}

console.log(`staging sketch library into ${stagedDir}`);
rmSync(stagedDir, { recursive: true, force: true });
mkdirSync(stagedDir, { recursive: true });

// --- 1. the lab's behaviour sketches ---------------------------------------
// Every top-level folder except `libraries/` is a category, and their names are
// not hardcoded anywhere — "Utility" and "Olfactory Behavior" are what this lab
// happens to have, not an enum.
for (const entry of readdirSync(behaviorRepo, { withFileTypes: true })) {
  if (!entry.isDirectory() || !isCategoryCandidate(entry.name)) continue;
  copyTree(join(behaviorRepo, entry.name), join(stagedDir, entry.name), entry.name);
}

// --- 2. the library collection ---------------------------------------------
// Only the ROOT `libraries/` reaches `arduino-cli --libraries`, so every sketch
// compiles against one predictable collection.
const librariesDir = join(stagedDir, "libraries");
mkdirSync(librariesDir, { recursive: true });

const source = join(behaviorRepo, "libraries");
if (existsSync(source)) {
  for (const entry of readdirSync(source, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    copyTree(join(source, entry.name), join(librariesDir, entry.name), `libraries/${entry.name}`);
  }
}

const total = countSketches(stagedDir);
const bytes = readdirSync(stagedDir, { withFileTypes: true, recursive: true })
  .filter((e) => e.isFile())
  .reduce((sum, e) => sum + statSync(join(e.parentPath, e.name)).size, 0);

console.log(`\n${total} sketches, ${Math.round(bytes / 1024)} KB`);

if (total === 0) {
  console.error("no valid sketches staged — check the source repo");
  process.exit(1);
}
