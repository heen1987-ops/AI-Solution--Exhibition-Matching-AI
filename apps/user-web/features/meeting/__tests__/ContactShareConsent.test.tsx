import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ContactShareConsent from "../components/ContactShareConsent";
import type { ContactShareField } from "../types";

function Harness() {
  const [checked, setChecked] = useState(false);
  const [fields, setFields] = useState<ContactShareField[]>(["NAME", "PHONE"]);
  const [showDetail, setShowDetail] = useState(false);
  return (
    <ContactShareConsent
      checked={checked}
      onCheckedChange={setChecked}
      selectedFields={fields}
      onToggleField={(field) =>
        setFields((prev) => (prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]))
      }
      showDetail={showDetail}
      onToggleDetail={() => setShowDetail((v) => !v)}
    />
  );
}

describe("ContactShareConsent", () => {
  it("defaults to unchecked - never pre-checked", () => {
    render(<Harness />);
    const checkbox = screen.getByRole("checkbox", { name: "수락 시 연락처를 공유합니다" });
    expect(checkbox).not.toBeChecked();
  });

  it("only becomes checked after an explicit user click", () => {
    render(<Harness />);
    const checkbox = screen.getByRole("checkbox", { name: "수락 시 연락처를 공유합니다" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("keeps the per-field checkboxes disabled until consent is checked", () => {
    render(<Harness />);
    fireEvent.click(screen.getByText("공유 항목 자세히 보기"));
    const nameField = screen.getByRole("checkbox", { name: "이름" }) as HTMLInputElement;
    expect(nameField.disabled).toBe(true);
  });
});
