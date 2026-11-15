/**
 * The version a "Ship main" build calls itself, and the check that it moves
 * the update feed forward (`.github/workflows/ship-main.yml`).
 *
 *   node scripts/ship-version.mjs <commit count> [feed version]
 *
 * Prints the version on stdout. Exits 1, saying why on stderr, when the feed
 * already holds that version or a newer one: installed copies only ever take a
 * newer version, so pointing the feed backwards would ship nothing.
 *
 * The version is `package.json`'s with main's commit count appended, so it
 * needs no commit to bump it and two builds of main never share one:
 *
 *   1.1.3-alpha  ->  1.1.3-alpha.214    above 1.1.3-alpha, below 1.1.4-alpha
 *   1.2.0        ->  1.2.1-main.214     above 1.2.0, below 1.2.1
 *
 * A tagged release (`release.yml`) bumps `package.json`, so the main builds
 * after it count up from that release rather than from below it.
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const SEMVER = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/;

function parse(version) {
  const m = SEMVER.exec(version);
  if (!m) throw new Error(`not a semver version: ${version}`);
  return {
    core: [Number(m[1]), Number(m[2]), Number(m[3])],
    pre: m[4] ? m[4].split(".") : [],
  };
}

export function shipVersion(base, count) {
  if (!Number.isInteger(count) || count < 1) throw new Error(`bad commit count: ${count}`);
  const { core, pre } = parse(base);
  if (pre.length) return `${core.join(".")}-${pre.join(".")}.${count}`;
  return `${core[0]}.${core[1]}.${core[2] + 1}-main.${count}`;
}

/** Semver precedence: negative when `a` is older than `b`. Build metadata is ignored. */
export function compareVersions(a, b) {
  const x = parse(a);
  const y = parse(b);
  for (let i = 0; i < 3; i++) {
    if (x.core[i] !== y.core[i]) return x.core[i] - y.core[i];
  }
  // A release outranks every pre-release of the same core.
  if (!x.pre.length || !y.pre.length) return y.pre.length - x.pre.length;
  for (let i = 0; i < Math.min(x.pre.length, y.pre.length); i++) {
    const p = x.pre[i];
    const q = y.pre[i];
    if (p === q) continue;
    const pNum = /^\d+$/.test(p);
    const qNum = /^\d+$/.test(q);
    if (pNum && qNum) return Number(p) - Number(q);
    if (pNum !== qNum) return pNum ? -1 : 1; // numeric identifiers sort first
    return p < q ? -1 : 1;
  }
  return x.pre.length - y.pre.length;
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const [count, feed] = process.argv.slice(2);
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const base = JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8")).version;
  const version = shipVersion(base, Number(count));
  if (feed && compareVersions(version, feed) <= 0) {
    console.error(
      `${version} is not newer than the feed's ${feed}; installed copies would not take it. ` +
        "Bump package.json past the feed's version first.",
    );
    process.exit(1);
  }
  console.log(version);
}
