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
 *
 * Both are read-only. Run `npm run gen:protocol` to fix the first; the second
 * is fixed by fixing the frontend.
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

const checks = [
  ["protocol", process.execPath, [join(repoRoot, "scripts", "gen-protocol.mjs"), "--check"]],
  ["typecheck", process.execPath, [tsc, "--noEmit"]],
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
