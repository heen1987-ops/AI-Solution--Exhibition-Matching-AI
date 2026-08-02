import { expect, test } from "vitest";
import { ADMIN_AREAS } from "../lib/admin-areas";

test("catalogues exactly the 14 future admin areas named in worker-prompts.md section F", () => {
  expect(ADMIN_AREAS).toHaveLength(14);

  const keys = ADMIN_AREAS.map((area) => area.key);
  expect(new Set(keys).size).toBe(keys.length);

  for (const area of ADMIN_AREAS) {
    expect(area.status).toBe("PLANNED");
    expect(area.title.length).toBeGreaterThan(0);
    expect(area.description.length).toBeGreaterThan(0);
  }
});
