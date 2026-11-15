import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SettingsFile } from "./settingsFile.js";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "ephymeris-settings-"));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe("SettingsFile", () => {
  it("reads the document Tauri's store plugin wrote", async () => {
    const path = join(dir, "settings.json");
    await writeFile(path, JSON.stringify({ settings: { dataDirectory: "D:\\data" } }));
    expect(await new SettingsFile(path).load()).toEqual({ dataDirectory: "D:\\data" });
  });

  it("is empty, not an error, before anything is saved", async () => {
    expect(await new SettingsFile(join(dir, "settings.json")).load()).toBeUndefined();
  });

  it("refuses a file that is not JSON", async () => {
    const path = join(dir, "settings.json");
    await writeFile(path, "{ not json");
    await expect(new SettingsFile(path).load()).rejects.toThrow();
  });

  it("saves in the same shape, keeping other keys, and leaves no temporary file", async () => {
    const path = join(dir, "nested", "settings.json");
    const file = new SettingsFile(path);
    await file.save({ a: 1 });
    await writeFile(path, JSON.stringify({ settings: { a: 1 }, other: true }));
    await file.save({ a: 2 });
    expect(JSON.parse(await readFile(path, "utf8"))).toEqual({ settings: { a: 2 }, other: true });
    expect(await readdir(join(dir, "nested"))).toEqual(["settings.json"]);
  });

  it("lands the last of several quick saves", async () => {
    const file = new SettingsFile(join(dir, "settings.json"));
    await Promise.all([file.save({ n: 1 }), file.save({ n: 2 }), file.save({ n: 3 })]);
    expect(await file.load()).toEqual({ n: 3 });
  });

  it("saves over an unreadable file", async () => {
    const path = join(dir, "settings.json");
    await writeFile(path, "{ not json");
    const file = new SettingsFile(path);
    await file.save({ fixed: true });
    expect(await file.load()).toEqual({ fixed: true });
  });
});
