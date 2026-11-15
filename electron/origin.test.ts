import { describe, expect, it } from "vitest";

import { appBase, isAppUrl } from "./origin.js";

const dev = appBase("http://localhost:1420/");
const installed = appBase(undefined);

describe("isAppUrl", () => {
  it("accepts the app's own pages under either base", () => {
    expect(isAppUrl("http://localhost:1420/index.html#/settings", dev)).toBe(true);
    expect(isAppUrl("app://ephymeris/index.html", installed)).toBe(true);
  });

  it("refuses anything else", () => {
    expect(isAppUrl("http://localhost:1421/", dev)).toBe(false);
    expect(isAppUrl("https://example.com/", dev)).toBe(false);
    expect(isAppUrl("app://other/index.html", installed)).toBe(false);
    expect(isAppUrl("file:///C:/index.html", installed)).toBe(false);
    expect(isAppUrl("not a url", installed)).toBe(false);
  });
});
