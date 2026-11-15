import { describe, expect, it } from "vitest";

import { appBase, isAppUrl, scopeUrl } from "./origin.js";

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

describe("scopeUrl", () => {
  it("resolves the route lib/intan/windows.ts asks for", () => {
    expect(scopeUrl("index.html#/scope/psth?box=1", dev)?.href).toBe(
      "http://localhost:1420/index.html#/scope/psth?box=1",
    );
    expect(scopeUrl("index.html#/scope/isi?box=2", installed)?.href).toBe(
      "app://ephymeris/index.html#/scope/isi?box=2",
    );
  });

  it("refuses a page that is not a scope, or not the app's", () => {
    expect(scopeUrl("index.html#/settings", dev)).toBeNull();
    expect(scopeUrl("https://example.com/#/scope/psth", dev)).toBeNull();
    expect(scopeUrl("//example.com/index.html#/scope/psth", dev)).toBeNull();
    expect(scopeUrl("other.html#/scope/psth", dev)).toBeNull();
  });
});
