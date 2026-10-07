/**
 * The logbook PDF actually renders, at length (`DATA.md#exporting-a-log`).
 *
 * The one test here that touches components, and on purpose: react-pdf needs
 * no DOM, and its failures are the kind no pure test sees. The footer once grew
 * with every page until, around page seven, the PDF writer refused a
 * coordinate of -2.6e21 and the whole export failed — invisible on the short
 * documents every other check used. So this renders a long one.
 */

import { renderToBuffer } from "@react-pdf/renderer";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { CohortLogbookDocument } from "@/components/logbook/pdf/documents";

import { forPrint, type DocCohort, type DocSession } from "./document";

function session(n: number): DocSession {
  const cell = { sampled: "60", rate: "70%", thin: false };
  return {
    id: `s${n}`,
    title: `2O-Bdisc_${n}`,
    date: "2026-10-02",
    longDate: "Friday 2 October 2026",
    status: "Completed",
    start: "09:00:00",
    end: "09:56:00",
    elapsed: "56:00",
    setup: "Set-up began 08:50:00",
    operator: "CJ",
    summary: "Steady session... remy3 slow to start -- check the spout.",
    notes: [
      { offset: "T+08:00", time: "09:08:00", tag: "Hardware", scope: "Box 2", body: "Beam flickers => re-seated.", flag: "carry forward" },
    ],
    performance: {
      conditions: ["Odor A → right", "Odor B → left"],
      rows: [1, 2, 3, 4, 5, 6].map((i) => ({
        animal: `remy${i}`,
        start: "09:00:00",
        end: "~09:56:00",
        cells: [cell, cell, { ...cell, thin: true }],
        note: null,
      })),
    },
    changes: [{ animal: "remy1", box: "box 1", parts: ["rewardUl 20 → 25"] }],
    changesNote: null,
  };
}

describe("the logbook PDF", () => {
  it("renders a long cohort, every page", async () => {
    const cohort: DocCohort = forPrint({
      cohortName: "Batch A",
      exportedAt: "06/10/2026, 22:00:00",
      span: "2026-05-01 – 2026-10-02",
      sessions: Array.from({ length: 40 }, (_, i) => session(i + 1)),
      noteCount: 40,
      openFlags: [{ body: "Box 2 beam", tag: "Hardware", scope: "Box 2", from: "2O-Bdisc_40" }],
    });
    const pdf = await renderToBuffer(createElement(CohortLogbookDocument, { cohort }) as never);
    const pages = (pdf.toString("latin1").match(/\/Type \/Page\b/g) ?? []).length;
    expect(pages).toBeGreaterThan(15);
  }, 60_000);
});
