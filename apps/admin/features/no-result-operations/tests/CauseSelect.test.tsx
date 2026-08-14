import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import CauseSelect from "../components/CauseSelect";
import { NO_RESULT_CAUSES } from "../logic";

// vitest.config.ts (shared, not owned by this track) does not enable test.globals, so
// @testing-library/react's auto-cleanup never registers - clean up explicitly instead of
// touching the shared config (same pattern as features/partner-ai-review).
afterEach(() => {
  cleanup();
});

describe("CauseSelect (cause-classification UI)", () => {
  it("lists all 8 spec-mandated causes as options", () => {
    render(<CauseSelect value="UNKNOWN" onChange={vi.fn()} />);
    const select = screen.getByRole("combobox", { name: "원인 분류" });
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.getAttribute("value"));
    expect(options).toEqual(NO_RESULT_CAUSES);
  });

  it("reflects the current value", () => {
    render(<CauseSelect value="SYNONYM_MISSING" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "원인 분류" })).toHaveValue("SYNONYM_MISSING");
  });

  it("calls onChange with the newly selected cause - the operator's choice only, nothing auto-inferred", () => {
    const onChange = vi.fn();
    render(<CauseSelect value="UNKNOWN" onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox", { name: "원인 분류" }), {
      target: { value: "ONTOLOGY_MISSING" },
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("ONTOLOGY_MISSING");
  });

  it("disables the control when disabled is set", () => {
    render(<CauseSelect value="UNKNOWN" onChange={vi.fn()} disabled />);
    expect(screen.getByRole("combobox", { name: "원인 분류" })).toBeDisabled();
  });
});
