import { describe, expect, it } from "vitest";

import { parseHandshake } from "./handshake.js";

describe("parseHandshake", () => {
  it("parses a well-formed handshake", () => {
    expect(parseHandshake("EPHYMERIS_WS_PORT=53834 EPHYMERIS_WS_TOKEN=abc123")).toEqual({
      port: 53834,
      token: "abc123",
    });
  });

  it("tolerates the line ending a Windows pipe leaves on", () => {
    expect(parseHandshake("EPHYMERIS_WS_PORT=53834 EPHYMERIS_WS_TOKEN=abc123\r")).toEqual({
      port: 53834,
      token: "abc123",
    });
  });

  it("ignores ordinary log lines", () => {
    expect(parseHandshake("sidecar listening on 127.0.0.1:53834")).toBeNull();
    expect(parseHandshake("EPHYMERIS_WS_PORT=53834")).toBeNull();
    expect(parseHandshake("EPHYMERIS_WS_PORT=notaport EPHYMERIS_WS_TOKEN=x")).toBeNull();
    expect(parseHandshake("EPHYMERIS_WS_PORT=70000 EPHYMERIS_WS_TOKEN=x")).toBeNull();
  });
});
