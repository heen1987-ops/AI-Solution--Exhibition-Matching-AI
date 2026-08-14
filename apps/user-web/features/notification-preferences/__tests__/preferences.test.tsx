/**
 * 알림 설정(`/notifications/preferences`) 테스트 (API 모킹).
 *
 * 작업 지시(WAVE 2E) 테스트 요구 중 이 파일이 담당하는 것: preference toggles -
 *   - 필수(운영) 알림은 토글 컨트롤 없이 "항상 알려드려요"로만 표시된다(끌 수 없음).
 *   - 선택 알림은 앱 내/이메일 채널별 토글을 갖는다.
 *   - 이메일 토글은 카테고리가 이메일 채널을 지원할 때만 렌더링되고, 등록된 이메일이
 *     없으면(email_on_file=false) 비활성 + 안내 문구로 표시된다.
 *   - 토글 성공 시 서버 응답을 정본으로 반영하고, 실패 시 이전 상태로 롤백 + 오류 표시.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";

// `tests/setup.ts`(공용, 이 트랙 소유 범위 밖)가 아직 `@testing-library/react`의 자동
// after-each cleanup을 활성화하지 않아 파일 내 여러 `render()`가 누적된다(다른 feature
// 테스트에서도 동일 패턴 - 공용 설정 이슈). 공용 파일을 건드리는 대신 이 파일 범위에서만
// 명시적으로 등록한다.
afterEach(cleanup);

import NotificationPreferencesPage from "@/app/notifications/preferences/page";
import PreferenceToggle from "../components/PreferenceToggle";
import type { NotificationCategoryPreference, NotificationPreferencesResponse } from "../types";

vi.mock("@/features/notification-preferences/api", () => ({
  getNotificationPreferences: vi.fn(),
  updateNotificationPreferences: vi.fn(),
}));

import { getNotificationPreferences, updateNotificationPreferences } from "../api";

const getMock = vi.mocked(getNotificationPreferences);
const updateMock = vi.mocked(updateNotificationPreferences);

function category(overrides: Partial<NotificationCategoryPreference> = {}): NotificationCategoryPreference {
  return {
    category_code: "RECOMMENDATION_READY",
    label: "추천 도착",
    description: "새 맞춤 추천이 준비되면 알려드려요.",
    mandatory: false,
    in_app_enabled: true,
    email_enabled: false,
    ...overrides,
  };
}

function response(overrides: Partial<NotificationPreferencesResponse> = {}): NotificationPreferencesResponse {
  return {
    email_on_file: true,
    categories: [
      category({
        category_code: "OPERATIONAL_NOTICE",
        label: "운영 공지",
        description: "행사 운영에 필요한 필수 안내예요.",
        mandatory: true,
        email_enabled: null,
      }),
      category(),
      category({
        category_code: "EVENT_DAY_REMINDER",
        label: "행사 당일 안내",
        description: "행사 당일 일정을 알려드려요.",
        email_enabled: true,
      }),
    ],
    ...overrides,
  };
}

beforeEach(() => {
  getMock.mockReset();
  updateMock.mockReset();
});

describe("PreferenceToggle", () => {
  it("is a keyboard-operable switch with a text state, not color alone", () => {
    render(<PreferenceToggle label="추천 도착 - 앱 내 알림" checked onChange={() => {}} />);
    const toggle = screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveTextContent("켬");
  });

  it("does not fire onChange when disabled", () => {
    const onChange = vi.fn();
    render(<PreferenceToggle label="이메일 알림" checked={false} disabled onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch", { name: "이메일 알림" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("NotificationPreferencesPage", () => {
  it("renders mandatory categories without any toggle control (cannot be disabled)", async () => {
    getMock.mockResolvedValue(response());
    render(<NotificationPreferencesPage />);
    await screen.findByText("운영 공지");
    const mandatoryItems = screen
      .getAllByTestId("preference-category")
      .filter((el) => el.getAttribute("data-mandatory") === "true");
    expect(mandatoryItems).toHaveLength(1);
    expect(mandatoryItems[0].querySelector('[role="switch"]')).toBeNull();
    expect(mandatoryItems[0].textContent).toContain("항상 알려드려요");
  });

  it("renders per-channel toggles for optional categories, hiding email when the channel is unsupported", async () => {
    getMock.mockResolvedValue(response());
    render(<NotificationPreferencesPage />);
    await screen.findByText("추천 도착");
    expect(screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "추천 도착 - 이메일 알림" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "행사 당일 안내 - 이메일 알림" })).toBeInTheDocument();
    // 필수 카테고리(email_enabled=null)는 이메일 토글 자체가 없다.
    expect(screen.queryByRole("switch", { name: /운영 공지/ })).not.toBeInTheDocument();
  });

  it("disables email toggles with an explanatory hint when no email is on file", async () => {
    getMock.mockResolvedValue(response({ email_on_file: false }));
    render(<NotificationPreferencesPage />);
    await screen.findByText("추천 도착");
    const emailToggle = screen.getByRole("switch", { name: "추천 도착 - 이메일 알림" });
    expect(emailToggle).toBeDisabled();
    expect(screen.getAllByText("이메일을 등록하면 사용할 수 있어요").length).toBeGreaterThan(0);
    // 비활성 토글 클릭이 저장 요청을 보내지 않는다.
    fireEvent.click(emailToggle);
    expect(updateMock).not.toHaveBeenCalled();
    // 앱 내 토글은 이메일 유무와 무관하게 동작한다.
    expect(screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" })).toBeEnabled();
  });

  it("sends only the toggled category/channel and adopts the server response as canonical", async () => {
    getMock.mockResolvedValue(response());
    updateMock.mockResolvedValue(
      response({
        categories: response().categories.map((c) =>
          c.category_code === "RECOMMENDATION_READY" ? { ...c, in_app_enabled: false } : c,
        ),
      }),
    );
    render(<NotificationPreferencesPage />);
    fireEvent.click(await screen.findByRole("switch", { name: "추천 도착 - 앱 내 알림" }));
    await waitFor(() =>
      expect(updateMock).toHaveBeenCalledWith({
        categories: [{ category_code: "RECOMMENDATION_READY", in_app_enabled: false }],
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" })).toHaveAttribute("aria-checked", "false"),
    );
  });

  it("rolls back the optimistic change and shows the error when saving fails", async () => {
    getMock.mockResolvedValue(response());
    updateMock.mockRejectedValue(
      new ApiClientError({
        code: "RESOURCE_FORBIDDEN",
        message: "설정을 저장할 수 없습니다.",
        field_errors: [],
        retryable: false,
        retry_after_seconds: null,
        http_status: 403,
        request_id: "req-2",
      }),
    );
    render(<NotificationPreferencesPage />);
    fireEvent.click(await screen.findByRole("switch", { name: "추천 도착 - 앱 내 알림" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("설정을 저장할 수 없습니다.");
    expect(screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" })).toHaveAttribute("aria-checked", "true");
  });

  it("shows an error state with retry when loading fails", async () => {
    getMock
      .mockRejectedValueOnce(
        new ApiClientError({
          code: "AUTH_REQUIRED",
          message: "로그인이 필요합니다.",
          field_errors: [],
          retryable: false,
          retry_after_seconds: null,
          http_status: 401,
          request_id: null,
        }),
      )
      .mockResolvedValueOnce(response());
    render(<NotificationPreferencesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("로그인이 필요합니다.");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("추천 도착")).toBeInTheDocument();
  });
});
