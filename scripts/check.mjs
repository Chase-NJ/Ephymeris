#!/usr/bin/env node
/**
 * Every generated artifact in this repo, verified against its source.
 *
 * Four things are generated and committed, and each has the same failure mode:
 * editing the source without regenerating leaves a mirror that still compiles,
 * still passes its own tests, and describes something that is no longer true.
 * `pytest` catches two of them; the other two had no gate at all until the fold
 * made `codegen` live.
 *
 *   protocol   protocol/schema.py  →  the Python and TypeScript wire mirrors
 *   typecheck  the frontend against those mirrors
 *   codegen    the compiler's registries  →  firmware/…/TaskInterpreter headers
 *   goldens    the paradigm registry  →  the listings the compiler tests pin
 *
 * All four are read-only. Run `npm run gen:protocol`, `taskgraph codegen` or
 * `taskgraph goldens` to fix whichever one fails.
 *
 * Everything is attempted even after a failure, because the useful answer to
 * "did my registry edit land everywhere" is the whole list, not the first
 * casualty of it.
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));

// The compiler's checks import `ephymeris_sidecar`, so unlike gen-protocol's
// stdlib-only generator they need the venv specifically — a system python would
// report a missing dependency as a failed check.
const venv = [
  join(repoRoot, "sidecar", ".venv", "Scripts", "python.exe"),
  join(repoRoot, "sidecar", ".venv", "bin", "python"),
].find(existsSync);

const npx = process.platform === "win32" ? "npx.cmd" : "npx";

const checks = [
  ["protocol", process.execPath, [join(repoRoot, "scripts", "gen-protocol.mjs"), "--check"]],
  ["typecheck", npx, ["tsc", "--noEmit"]],
  ["codegen", venv, ["-m", "ephymeris_sidecar.taskgraph.cli", "codegen", "--check"]],
  ["goldens", venv, ["-m", "ephymeris_sidecar.taskgraph.cli", "goldens", "--check"]],
];

const failed = [];

for (const [name, cmd, args] of checks) {
  if (!cmd) {
    console.error(`\n=== ${name} — SKIPPED: no sidecar venv (see README) ===`);
    failed.push(name);
    continue;
  }
  console.log(`\n=== ${name} ===`);
  const result = spawnSync(cmd, args, { stdio: "inherit", cwd: repoRoot });
  if (result.status !== 0) failed.push(name);
}

if (failed.length > 0) {
  console.error(`\n${failed.length} of ${checks.length} failed: ${failed.join(", ")}`);
  process.exit(1);
}
console.log(`\nall ${checks.length} checks current`);
