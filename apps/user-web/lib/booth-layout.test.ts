import { describe, expect, it } from "vitest";

import { BOOTH_LAYOUT_SCOPE, BOOTH_LAYOUT_STATUS, PROVISIONAL_BOOTH_COLUMNS } from "./booth-layout";

describe("provisional booth layout", () => {
  it("keeps the single-hall reference explicitly provisional", () => {
    expect(BOOTH_LAYOUT_STATUS).toBe("DRAFT_REFERENCE");
    expect(BOOTH_LAYOUT_SCOPE).toBe("EXCO_HALL_3_SINGLE_HALL");
    expect(PROVISIONAL_BOOTH_COLUMNS.map((column) => column.id)).toEqual(["Q", "R", "S"]);
    expect(PROVISIONAL_BOOTH_COLUMNS.flatMap((column) => column.booths).every((cell) => cell.status === "PROVISIONAL")).toBe(true);
  });

  it("uses planning codes without assigning exhibitors", () => {
    const cells = PROVISIONAL_BOOTH_COLUMNS.flatMap((column) => column.booths);

    expect(cells.length).toBeGreaterThan(0);
    expect(cells.every((cell) => /^[QRS]-\d{2}$/.test(cell.code))).toBe(true);
    expect(new Set(cells.map((cell) => cell.code)).size).toBe(cells.length);
  });
});
