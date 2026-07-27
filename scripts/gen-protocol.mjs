#!/usr/bin/env node
/**
 * Cross-platform launcher for the wire-protocol generator.
 *
 * `protocol/generate.py` is stdlib-only, so any Python ≥ 3.9 works; this shim
 * exists because the interpreter is called `python3` on macOS, `python` (or
 * `py`) on Windows, and lives in `sidecar/.venv` on a set-up dev machine. It
 * tries the venv first, then the system names, and forwards arguments
 * (`--check`) and the exit code verbatim.
 */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const generator = join(repoRoot, "protocol", "generate.py");

const candidates = [
  join(repoRoot, "sidecar", ".venv", "Scripts", "python.exe"), // Windows venv
  join(repoRoot, "sidecar", ".venv", "bin", "python"), // POSIX venv
  "python3",
  "python",
  "py",
].filter((cmd) => !cmd.includes(".venv") || existsSync(cmd));

for (const python of candidates) {
  const result = spawnSync(python, [generator, ...process.argv.slice(2)], {
    stdio: "inherit",
  });
  // ENOENT means this candidate doesn't exist — try the next. Any real run,
  // pass or fail, is final: a --check failure must not fall through.
  if (result.error && result.error.code === "ENOENT") continue;
  process.exit(result.status ?? 1);
}

console.error(
  "gen-protocol: no Python interpreter found (tried sidecar/.venv, python3, python, py)",
);
process.exit(1);
