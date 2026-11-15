import { describe, expect, it } from "vitest";

import type { FlashJobStatus, FlashQueueStatus } from "../ws/protocol";
import { resumeWalkAt, sessionFlashCards } from "./flashCards";

function job(state: FlashJobStatus["state"], origin: FlashJobStatus["origin"] = "session", detail: string | null = null): FlashJobStatus {
  return { origin, sketchPath: "/sk/GRGL", sketchName: "GRGL", state, detail };
}

function queue(jobs: Record<number, FlashJobStatus | null>): FlashQueueStatus {
  return {
    boxes: [1, 2, 3, 4, 5, 6].map((box) => ({ box, job: jobs[box] ?? null, carries: null })),
  };
}

describe("sessionFlashCards", () => {
  it("reads a box with nothing queued, and every box before a confirm, as idle", () => {
    expect(sessionFlashCards(null, [1, 2]).cards.get(1)).toEqual({ state: "idle", detail: null });
    const { cards, pending, allFlashed } = sessionFlashCards(queue({}), [1, 2]);
    expect(cards.get(2)!.state).toBe("idle");
    expect(pending).toBe(false);
    expect(allFlashed).toBe(false);
  });

  it("ignores a Debug flash or a restore of the same box", () => {
    const status = queue({ 1: job("done", "debug"), 2: job("flashing", "baseline") });
    const { cards, flashedCount } = sessionFlashCards(status, [1, 2]);
    expect(cards.get(1)!.state).toBe("idle");
    expect(cards.get(2)!.state).toBe("idle");
    expect(flashedCount).toBe(0);
  });

  it("shows a job waiting for its port as queued, with the sidecar's reason", () => {
    const status = queue({ 1: job("waiting", "session", "waiting for the port (flashing)") });
    expect(sessionFlashCards(status, [1]).cards.get(1)).toEqual({
      state: "queued",
      detail: "waiting for the port (flashing)",
    });
  });

  it("counts done boxes and is pending while any is queued or flashing", () => {
    const status = queue({ 1: job("done"), 2: job("flashing"), 3: job("failed", "session", "compile failed") });
    const flashes = sessionFlashCards(status, [1, 2, 3]);
    expect(flashes.flashedCount).toBe(1);
    expect(flashes.pending).toBe(true);
    expect(flashes.allFlashed).toBe(false);
    expect(flashes.cards.get(3)).toEqual({ state: "failed", detail: "compile failed" });
  });

  it("is all flashed only when every mapped box is", () => {
    const status = queue({ 1: job("done"), 2: job("done") });
    expect(sessionFlashCards(status, [1, 2]).allFlashed).toBe(true);
    expect(sessionFlashCards(status, [1, 2, 3]).allFlashed).toBe(false);
    expect(sessionFlashCards(status, []).allFlashed).toBe(false);
  });
});

describe("resumeWalkAt", () => {
  it("has nothing to resume when no session flash was asked for", () => {
    expect(resumeWalkAt(queue({ 2: job("done", "debug") }), [1, 2, 3])).toBeNull();
    expect(resumeWalkAt(null, [1, 2, 3])).toBeNull();
  });

  it("resumes at the first box in walk order nobody asked to flash", () => {
    const status = queue({ 1: job("done"), 2: job("queued") });
    expect(resumeWalkAt(status, [1, 2, 3, 5])).toBe(2);
  });

  it("is past the end once every box was asked for and one still needs attention", () => {
    expect(resumeWalkAt(queue({ 1: job("done"), 2: job("failed") }), [1, 2])).toBe(2);
    expect(resumeWalkAt(queue({ 1: job("done"), 2: job("flashing") }), [1, 2])).toBe(2);
  });

  it("does not resume a walk whose every box flashed", () => {
    // Mission Control's Back to Boxes: a board stopped carrying its sketch.
    // Resuming would read "all flashed" and bounce straight back.
    expect(resumeWalkAt(queue({ 1: job("done"), 2: job("done") }), [1, 2])).toBeNull();
  });
});
