#!/usr/bin/env node
/**
 * Every generated artifact in this repo, verified against its source.
 *
 * Two things are generated and committed, and they share a failure mode:
 * editing the source without regenerating leaves a mirror that still compiles,
 * still passes its own tests, and describes something that is no longer true.
 *
 *   protocol   protocol/schema.py  →  the Python and TypeScript wire mirrors
 *   typecheck  the frontend against those mirrors
 *   unit       the frontend's pure layer (`src/lib/**`)
 *
 * All read-only. Run `npm run gen:protocol` to fix the first; the others are
 * fixed by fixing the frontend.
 *
 * The unit tests joined this list rather than staying a separate command
 * because what they cover is the same class of failure the other two do:
 * `topology.ts` and `graphLayout.ts` decode and lay out a drawing that looks
 * deliberate when it is wrong, so a green typecheck says nothing about them.
 *
 * Everything is attempted even after a failure, because the useful answer to
 * "did my schema edit land everywhere" is the whole list, not the first
 * casualty of it.
 */

import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));

// `tsc` is run through Node against the package's own entry point rather than
// through `npx`. On Windows `npx` is `npx.cmd`, and since Node closed
// CVE-2024-27980 `spawnSync` refuses to launch a `.cmd` without a shell — it
// fails `EINVAL` with `status: null`, which this script then reported as a
// failing typecheck. The check looked like it was running for as long as it
// happened to agree with reality.
const tsc = join(repoRoot, "node_modules", "typescript", "bin", "tsc");
// Same reasoning as `tsc` above — the package's own entry point, never `npx`.
const vitest = join(repoRoot, "node_modules", "vitest", "vitest.mjs");

const checks = [
  ["protocol", process.execPath, [join(repoRoot, "scripts", "gen-protocol.mjs"), "--check"]],
  ["typecheck", process.execPath, [tsc, "--noEmit"]],
  ["unit", process.execPath, [vitest, "run"]],
];

const failed = [];

for (const [name, cmd, args] of checks) {
  console.log(`\n=== ${name} ===`);
  const result = spawnSync(cmd, args, { stdio: "inherit", cwd: repoRoot });
  if (result.status !== 0) failed.push(name);
}

if (failed.length > 0) {
  console.error(`\n${failed.length} of ${checks.length} failed: ${failed.join(", ")}`);
  process.exit(1);
}
console.log(`\nall ${checks.length} checks current`);
