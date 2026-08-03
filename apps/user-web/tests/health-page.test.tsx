import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HealthPage from "../app/health/page";

describe("/health 프런트엔드 빌드·환경 상태 화면", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("환경변수가 설정된 경우 OK 배지를 보여준다", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000");
    vi.stubEnv("NEXT_PUBLIC_APP_ENV", "local");

    render(<HealthPage />);

    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getByText("http://localhost:8000")).toBeInTheDocument();
  });

  it("NEXT_PUBLIC_API_BASE_URL이 없으면 경고 상태를 보여준다", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    vi.stubEnv("NEXT_PUBLIC_APP_ENV", "local");

    render(<HealthPage />);

    expect(screen.getByText("환경변수 확인 필요")).toBeInTheDocument();
    expect(screen.getByText("미설정")).toBeInTheDocument();
  });
});
