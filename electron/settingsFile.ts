/**
 * `settings.json` in the app data directory (`ARCHITECTURE.md#persistence-and-push`),
 * in the shape Tauri's store plugin left it, `{ "settings": { … } }`, so the
 * file an operator already has is read as-is after the switch of shells.
 *
 * Written whole to a temporary file and renamed over the old one, so a crash
 * mid-write leaves the previous settings rather than half of the new ones.
 * Saves run one at a time, in the order they were asked for.
 */

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const KEY = "settings";

export class SettingsFile {
  private queue: Promise<void> = Promise.resolve();

  constructor(readonly path: string) {}

  /** The stored settings, unvalidated; undefined when nothing is stored yet. */
  async load(): Promise<unknown> {
    const document = await this.readDocument();
    return document?.[KEY];
  }

  save(settings: unknown): Promise<void> {
    const write = this.queue.then(() => this.write(settings));
    // A failed save is reported to its caller and does not block the next one.
    this.queue = write.catch(() => {});
    return write;
  }

  private async write(settings: unknown): Promise<void> {
    // Keep any other keys the file carries; this shell owns only `settings`.
    let document: Record<string, unknown> = {};
    try {
      document = (await this.readDocument()) ?? {};
    } catch {
      // Unreadable: the operator is saving over it from defaults anyway.
    }
    document[KEY] = settings;
    await mkdir(dirname(this.path), { recursive: true });
    const temporary = `${this.path}.${process.pid}.tmp`;
    await writeFile(temporary, `${JSON.stringify(document, null, 2)}\n`, "utf8");
    await rename(temporary, this.path);
  }

  private async readDocument(): Promise<Record<string, unknown> | undefined> {
    let text: string;
    try {
      text = await readFile(this.path, "utf8");
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return undefined;
      throw err;
    }
    const parsed: unknown = JSON.parse(text);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${this.path} is not a settings document`);
    }
    return parsed as Record<string, unknown>;
  }
}
