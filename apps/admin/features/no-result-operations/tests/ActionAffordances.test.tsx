import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ActionAffordances from "../components/ActionAffordances";

afterEach(() => {
  cleanup();
});

describe("ActionAffordances (action affordances UI)", () => {
  it("only renders actions allowed for the given cause, plus both terminal actions", () => {
    render(<ActionAffordances cause="NO_ELIGIBLE_EXHIBITOR" onAction={vi.fn()} />);
    // NO_ELIGIBLE_EXHIBITOR has no non-terminal affordances (logic.test.ts asserts this too).
    expect(screen.getByRole("button", { name: /해결됨으로 표시/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /무시로 표시/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /재인덱싱 요청/ })).not.toBeInTheDocument();
  });

  it("renders cause-specific non-terminal actions", () => {
    render(<ActionAffordances cause="INDEXING_DELAY" onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: /재인덱싱 요청/ })).toBeInTheDocument();
  });

  it("disables the ignore action until a note is entered, then enables it", () => {
    render(<ActionAffordances cause="UNKNOWN" onAction={vi.fn()} />);
    const ignoreButton = screen.getByRole("button", { name: /무시로 표시/ });
    expect(ignoreButton).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: "개선 액션 메모" }), {
      target: { value: "중복 질의" },
    });
    expect(ignoreButton).toBeEnabled();
  });

  it("calls onAction with the trimmed note for the clicked action", () => {
    const onAction = vi.fn();
    render(<ActionAffordances cause="UNKNOWN" onAction={onAction} />);
    fireEvent.change(screen.getByRole("textbox", { name: "개선 액션 메모" }), {
      target: { value: "  동의어 후보: 왕대포  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /동의어 추가 요청/ }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("REQUEST_SYNONYM_ADDITION", "동의어 후보: 왕대포");
  });

  it("calls onAction with a null note when no note was entered for a non-terminal action", () => {
    const onAction = vi.fn();
    render(<ActionAffordances cause="INDEXING_DELAY" onAction={onAction} />);
    fireEvent.click(screen.getByRole("button", { name: /재인덱싱 요청/ }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction).toHaveBeenCalledWith("REQUEST_REINDEX", null);
  });

  it("disables every button while busy", () => {
    render(<ActionAffordances cause="INDEXING_DELAY" onAction={vi.fn()} busy />);
    expect(screen.getByRole("button", { name: /재인덱싱 요청/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /해결됨으로 표시/ })).toBeDisabled();
  });
});
