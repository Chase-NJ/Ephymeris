import { describe, expect, it } from "vitest";

import { TABLE_FITS_CONDITIONS, shortClock, tableMinWidth, tableTemplate } from "./session";

/** The Log's readout at the lab machines' 1920px, the narrower of the two
 *  homes the table has (`max-w-6xl` less the rail, its gap and padding). */
const LOG_READOUT_PX = 770;

describe("session table layout", () => {
  it("fits ten conditions in the Log without scrolling", () => {
    expect(tableMinWidth(TABLE_FITS_CONDITIONS)).toBeLessThanOrEqual(LOG_READOUT_PX);
  });

  it("has one column per condition after the animal and pooled ones", () => {
    expect(tableTemplate(3).split(" ")).toHaveLength(5);
  });

  it("shortens a clock and leaves anything else alone", () => {
    expect(shortClock("09:05:31")).toBe("09:05");
    expect(shortClock("—")).toBe("—");
  });
});
