import { describe, expect, it } from "vitest";

import { ERR, SidecarCommandError } from "../ws/protocol";
import { boxesNeedingFlash } from "./commands";

const refusal = (code: string, detail: unknown) =>
  new SidecarCommandError({ code, message: "Nothing was started", detail });

describe("boxesNeedingFlash", () => {
  it("reads the boxes off a start refused for unflashed boards", () => {
    expect(boxesNeedingFlash(refusal(ERR.SESSION_INVALID, { boxes: [2, 5] }))).toEqual([2, 5]);
  });

  it("is null for every other failure", () => {
    expect(boxesNeedingFlash(refusal(ERR.SESSION_INVALID, { box: 2 }))).toBeNull();
    expect(boxesNeedingFlash(refusal(ERR.SESSION_INVALID, null))).toBeNull();
    expect(boxesNeedingFlash(refusal(ERR.SESSION_INVALID, { boxes: [] }))).toBeNull();
    expect(boxesNeedingFlash(refusal(ERR.ILLEGAL_TRANSITION, { boxes: [2] }))).toBeNull();
    expect(boxesNeedingFlash(new Error("socket closed"))).toBeNull();
  });
});
