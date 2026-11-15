/**
 * Spawns and supervises the Python sidecar (`ARCHITECTURE.md#process-lifecycle`).
 * A port of `src-tauri/src/sidecar.rs`.
 *
 * The sidecar binds an ephemeral loopback port and prints one handshake line
 * on stdout (`handshake.ts`). The endpoint is held here for a window that asks
 * late and announced to every window as it arrives. The child's stdin is held
 * open for the life of the app: its EOF is how the sidecar learns the shell is
 * gone, even when this process is killed outright. Never respawned.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";

import type { SidecarEndpoint } from "./bridge.js";
import { parseHandshake } from "./handshake.js";
import type { Launch } from "./launch.js";

export interface SidecarEvents {
  ready(endpoint: SidecarEndpoint): void;
  /** The sidecar exited or never started. Sent once. */
  down(): void;
}

export class Sidecar {
  private child: ChildProcess | null = null;
  private current: SidecarEndpoint | null = null;
  private downSent = false;

  constructor(private readonly events: SidecarEvents) {}

  /** Null until the handshake, and again once the sidecar has exited. */
  get endpoint(): SidecarEndpoint | null {
    return this.current;
  }

  start(launch: Launch, dataDir: string, env: Record<string, string>): void {
    const args = [...launch.args, "--data-dir", dataDir];
    console.info(`spawning sidecar: ${launch.program} ${args.join(" ")}`);

    const child = spawn(launch.program, args, {
      cwd: launch.cwd,
      env: {
        ...process.env,
        // Python picks its text encoding from the locale at interpreter
        // startup, which on the lab PCs is cp1252: a task spec with an em
        // dash or a µ would decode to mojibake. Only the environment is early
        // enough to fix that.
        PYTHONUTF8: "1",
        ...env,
      },
      stdio: ["pipe", "pipe", "pipe"],
      // The frozen sidecar is a console binary; without this every launch
      // flashes a console window on Windows.
      windowsHide: true,
    });
    this.child = child;

    child.on("error", (err) => {
      console.error(`sidecar failed to start: ${err.message}`);
      this.markDown();
    });
    // Writing to a dead sidecar's stdin raises EPIPE asynchronously; nothing is
    // ever written, but an unhandled stream error would take this process down.
    child.stdin?.on("error", () => {});

    if (child.stdout) {
      const lines = createInterface({ input: child.stdout, crlfDelay: Infinity });
      lines.on("line", (line) => {
        const endpoint = parseHandshake(line);
        if (endpoint) {
          console.info(`sidecar ready on port ${endpoint.port}`);
          this.current = endpoint;
          this.events.ready(endpoint);
        }
      });
      lines.on("close", () => {
        console.warn("sidecar stdout closed; process has exited");
        this.markDown();
      });
    }

    if (child.stderr) {
      const lines = createInterface({ input: child.stderr, crlfDelay: Infinity });
      lines.on("line", (line) => console.info(`[sidecar] ${line}`));
    }
  }

  /**
   * Let the sidecar shut itself down, then kill it if it has not by `graceMs`.
   *
   * For handing the install over to an updater, where a plain kill is not
   * enough: closing stdin runs the sidecar's normal shutdown, which stops the
   * `arduino-cli` daemon and waits for it (an installer that starts first
   * finds `arduino-cli.exe` still locked) and closes the database.
   */
  async stop(graceMs: number): Promise<void> {
    const child = this.child;
    if (!child || exited(child)) return;
    const gone = new Promise<void>((resolve) => child.once("exit", () => resolve()));
    child.stdin?.end();
    const timer = new Promise<"timeout">((resolve) => setTimeout(() => resolve("timeout"), graceMs));
    if ((await Promise.race([gone, timer])) === "timeout") {
      console.warn(`sidecar still running after ${graceMs} ms; killing it`);
      child.kill();
      await gone;
    }
    this.child = null;
  }

  /** On app exit: the sidecar must never outlive the shell holding serial ports. */
  shutdown(): void {
    const child = this.child;
    this.child = null;
    if (!child || exited(child)) return;
    child.stdin?.end();
    child.kill();
  }

  private markDown(): void {
    this.current = null;
    if (this.downSent) return;
    this.downSent = true;
    this.events.down();
  }
}

function exited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}
