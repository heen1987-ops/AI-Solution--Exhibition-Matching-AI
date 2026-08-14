import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AlternateTimePicker from "../components/AlternateTimePicker";
import type { SlotCandidate } from "../types";

const slots: SlotCandidate[] = [
  {
    slot_id: "s1",
    start_at: "2026-08-05T02:00:00Z",
    end_at: "2026-08-05T02:30:00Z",
    preference_order: 1,
    request_status: "SELECTED",
  },
];

describe("AlternateTimePicker", () => {
  it("accepts the exhibitor's proposed time when the accept button is pressed", () => {
    const onAccept = vi.fn();
    const onDeclineAll = vi.fn();
    render(
      <AlternateTimePicker candidateSlots={slots} isActing={false} onAccept={onAccept} onDeclineAll={onDeclineAll} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "이 시간 수락" }));
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onDeclineAll).not.toHaveBeenCalled();
  });

  it("declines all proposed times when the decline button is pressed", () => {
    const onAccept = vi.fn();
    const onDeclineAll = vi.fn();
    render(
      <AlternateTimePicker candidateSlots={slots} isActing={false} onAccept={onAccept} onDeclineAll={onDeclineAll} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "모두 거절" }));
    expect(onDeclineAll).toHaveBeenCalledTimes(1);
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("disables both actions while a request is in flight", () => {
    render(
      <AlternateTimePicker candidateSlots={slots} isActing={true} onAccept={vi.fn()} onDeclineAll={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "이 시간 수락" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "모두 거절" })).toBeDisabled();
  });
});
