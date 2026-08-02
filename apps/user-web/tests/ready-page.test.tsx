import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ReadyPage from "../app/page";

describe("/ 사용자 웹 준비 화면", () => {
  it("준비 화면 문구와 이동 링크를 렌더링한다", () => {
    render(<ReadyPage />);

    expect(screen.getByText("사용자 웹 준비 화면")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /빌드·환경 상태 보기/ })).toHaveAttribute(
      "href",
      "/health",
    );
    expect(screen.getByRole("link", { name: /화면 뼈대 둘러보기/ })).toHaveAttribute(
      "href",
      "/home",
    );
  });
});
