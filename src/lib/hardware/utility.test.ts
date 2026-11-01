import { describe, expect, it } from "vitest";

import type { ControlSetting } from "@/lib/ws/protocol";

import { readSetting, settingChoices } from "./utility";

const DUTY: ControlSetting = {
  label: "Duty",
  state: "house.duty",
  options: [
    { label: "50%", value: "128", command: "DUTY house 128" },
    { label: "100%", value: "255", command: "DUTY house 255" },
  ],
};

describe("readSetting", () => {
  it("reads the option the board reports", () => {
    expect(readSetting(DUTY, ["255"])).toEqual({ kind: "value", value: "255", label: "100%" });
  });

  it("shows a value no option offers as the board's own number", () => {
    // Typed at the console: `DUTY house 77`.
    expect(readSetting(DUTY, ["77"])).toEqual({ kind: "value", value: "77", label: "77" });
  });

  it("claims nothing before the board has reported", () => {
    expect(readSetting(DUTY, [undefined])).toEqual({ kind: "none" });
    expect(readSetting(DUTY, [])).toEqual({ kind: "none" });
  });

  it("across boxes, agrees only when every reporting box does", () => {
    expect(readSetting(DUTY, ["128", undefined, "128"])).toEqual({ kind: "value", value: "128", label: "50%" });
    expect(readSetting(DUTY, ["128", "255"])).toEqual({ kind: "mixed" });
  });
});

describe("settingChoices", () => {
  it("is the options, with the current one selected", () => {
    const { value, options } = settingChoices(DUTY, { kind: "value", value: "128", label: "50%" });
    expect(value).toBe("DUTY house 128");
    expect(options).toEqual([
      { value: "DUTY house 128", label: "50%" },
      { value: "DUTY house 255", label: "100%" },
    ]);
  });

  it("puts a placeholder first for anything that is not an option", () => {
    expect(settingChoices(DUTY, { kind: "value", value: "77", label: "77" }).options[0]).toEqual({
      value: "",
      label: "77",
    });
    expect(settingChoices(DUTY, { kind: "mixed" }).options[0]).toEqual({ value: "", label: "mixed" });
    const none = settingChoices(DUTY, { kind: "none" });
    expect(none.value).toBe("");
    expect(none.options.map((o) => o.label)).toEqual(["—", "50%", "100%"]);
  });
});
