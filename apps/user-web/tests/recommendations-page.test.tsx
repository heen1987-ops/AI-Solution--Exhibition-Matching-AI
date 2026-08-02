import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import RecommendationsPage from "../app/(screens)/recommendations/page";

describe("S-2 추천 업체·부스 목록 (Mock)", () => {
  it("기본 시나리오에서 추천 카드를 렌더링한다", async () => {
    const element = await RecommendationsPage({
      searchParams: Promise.resolve({}),
    });
    render(element);

    expect(screen.getByText("추천 업체·부스 목록")).toBeInTheDocument();
    expect(screen.getByText("지리산 목재가공")).toBeInTheDocument();
  });

  it("?state=empty 시나리오에서 빈 결과 상태를 렌더링한다", async () => {
    const element = await RecommendationsPage({
      searchParams: Promise.resolve({ state: "empty" }),
    });
    render(element);

    expect(screen.getByRole("status")).toHaveTextContent("아직 추천할 업체가 없습니다");
  });

  it("?state=error 시나리오에서는 Mock 오류를 throw한다(error.tsx가 처리)", async () => {
    // 참고: 이 워크스페이스에서는 vitest.rejects.toThrow(string)이 hoisted된
    // 루트 chai(5.3.3)와 충돌해 "Cannot read properties of undefined (reading
    // 'indexOf')"를 던진다(별개 앱 간 npm workspaces 버전 호이스팅 이슈로 판단,
    // WEB-001 범위 밖) - 그래서 try/catch로 직접 검증한다.
    let caught: unknown;
    try {
      await RecommendationsPage({ searchParams: Promise.resolve({ state: "error" }) });
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("MOCK_RECOMMENDATION_FETCH_FAILED");
  });
});
