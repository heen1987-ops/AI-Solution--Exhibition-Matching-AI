import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest.config.ts has `test.globals` unset (false), so @testing-library/react's
// own auto-cleanup detection (which looks for a global `afterEach`) never fires.
// Without this, DOM nodes from one test/`it.each` case leak into the next,
// producing "Found multiple elements" failures across files that render the
// same component more than once (WAVE 2C/2D/2E discovered this the hard way).
afterEach(() => {
  cleanup();
});
