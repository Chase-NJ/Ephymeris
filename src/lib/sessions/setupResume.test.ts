import { afterEach, describe, expect, it } from "vitest";

import {
  clearSetupResume,
  getSetupDraft,
  getSetupResume,
  noteLocation,
  setSetupDraft,
  setupStepOf,
} from "./setupResume";

afterEach(() => {
  clearSetupResume();
});

describe("setupStepOf", () => {
  it("names each setup step and the session it belongs to", () => {
    expect(setupStepOf("/session/new")).toEqual({ step: "configure", sessionId: null });
    expect(setupStepOf("/session/abc/group")).toEqual({ step: "group", sessionId: "abc" });
    expect(setupStepOf("/session/abc/mapping")).toEqual({ step: "boxes", sessionId: "abc" });
    expect(setupStepOf("/session/abc/recording")).toEqual({ step: "record", sessionId: "abc" });
  });

  it("tells Mission Control apart from the setup steps", () => {
    expect(setupStepOf("/session/abc/control")).toBe("control");
  });

  it("is null everywhere else, including the Recording settings tab", () => {
    for (const path of ["/", "/config", "/recording", "/task/new", "/debug", "/session"]) {
      expect(setupStepOf(path)).toBeNull();
    }
  });
});

describe("noteLocation", () => {
  it("remembers the last setup step, exactly as it was left", () => {
    noteLocation("/session/abc/mapping", "?cohort=c&group=g");
    noteLocation("/config/wiring", "");
    expect(getSetupResume()).toEqual({
      url: "/session/abc/mapping?cohort=c&group=g",
      step: "boxes",
      sessionId: "abc",
    });
  });

  it("forgets it once Mission Control is reached", () => {
    noteLocation("/session/abc/recording", "?cohort=c&group=g");
    noteLocation("/session/abc/control", "?cohort=c&group=g");
    expect(getSetupResume()).toBeNull();
  });
});

describe("drafts", () => {
  it("survive a visit elsewhere and are dropped when the set-up ends", () => {
    noteLocation("/session/new", "?mode=recording");
    setSetupDraft("configure:recording", { sessionNumber: "7" });
    noteLocation("/config", "");
    expect(getSetupDraft("configure:recording")).toEqual({ sessionNumber: "7" });

    noteLocation("/session/abc/control", "?cohort=c");
    expect(getSetupDraft("configure:recording")).toBeUndefined();
  });

  it("are dropped by a deliberate cancel", () => {
    noteLocation("/session/abc/mapping", "?cohort=c&group=g");
    setSetupDraft("boxes:abc:g", []);
    clearSetupResume();
    expect(getSetupDraft("boxes:abc:g")).toBeUndefined();
    expect(getSetupResume()).toBeNull();
  });
});
