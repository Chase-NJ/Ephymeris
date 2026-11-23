import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { bundledEnv, resolveLaunch, type LaunchContext } from "./launch.js";

const REPO = join("/", "repo");
const RES = join("/", "app", "resources");
const VENV_PY = join(REPO, "sidecar", ".venv", "Scripts", "python.exe");
const FROZEN = join(RES, "sidecar", "ephymeris-sidecar.exe");

function context(files: string[], overrides: Partial<LaunchContext> = {}): LaunchContext {
  const present = new Set(files);
  return {
    explicitPython: undefined,
    packaged: false,
    repoRoot: REPO,
    resourcesPath: RES,
    windows: true,
    isFile: (path) => present.has(path),
    isDirectory: (path) => present.has(path),
    ...overrides,
  };
}

describe("resolveLaunch", () => {
  it("runs the venv from a checkout when both exist", () => {
    const launch = resolveLaunch(context([VENV_PY, FROZEN]));
    expect(launch).toEqual({ program: VENV_PY, args: ["-m", "ephymeris_sidecar"], cwd: join(REPO, "sidecar") });
  });

  it("runs the frozen exe from an installed build when both exist", () => {
    const launch = resolveLaunch(context([VENV_PY, FROZEN], { packaged: true }));
    expect(launch).toEqual({ program: FROZEN, args: [], cwd: join(RES, "sidecar") });
  });

  it("falls back to the other when the preferred one is missing", () => {
    expect(resolveLaunch(context([FROZEN])).program).toBe(FROZEN);
    expect(resolveLaunch(context([VENV_PY], { packaged: true })).program).toBe(VENV_PY);
  });

  it("lets EPHYMERIS_SIDECAR_PYTHON win over both, as a module run", () => {
    const launch = resolveLaunch(context([VENV_PY, FROZEN], { explicitPython: "/opt/py", packaged: true }));
    expect(launch).toEqual({ program: "/opt/py", args: ["-m", "ephymeris_sidecar"], cwd: join(REPO, "sidecar") });
  });

  it("says how to fix it when there is no sidecar at all", () => {
    expect(() => resolveLaunch(context([]))).toThrow(/create the venv/);
  });

  it("names the POSIX interpreter off Windows", () => {
    const python = join(REPO, "sidecar", ".venv", "bin", "python");
    expect(resolveLaunch(context([python], { windows: false })).program).toBe(python);
  });
});

describe("bundledEnv", () => {
  it("exports only the resources that exist", () => {
    const cli = join(RES, "arduino", "arduino-cli.exe");
    const sketches = join(RES, "sketches");
    const tasksim = join(RES, "tasksim");
    expect(bundledEnv(context([cli, sketches, tasksim]))).toEqual({
      EPHYMERIS_BUNDLED_ARDUINO_CLI: cli,
      EPHYMERIS_BUNDLED_SKETCHES: sketches,
      EPHYMERIS_BUNDLED_TASK_SIM: tasksim,
    });
    expect(bundledEnv(context([]))).toEqual({});
  });
});
