"use client";

/**
 * API 오류를 화면에 정직하게 보여주는 공용 배너.
 *
 * 작업 지시: "화면과 상태관리는 실제로 동작하게 만들되 백엔드가 없으면 명확한 오류
 * 상태로 표시해라(가짜 성공 표시 금지)." `code === "NOT_IMPLEMENTED"`(백엔드 라우터
 * 자체가 없음, lib/api-client.ts 참고)는 노란색 "미구현" 톤으로, 그 외 실제 오류(권한
 * 없음, 검증 실패, 네트워크 등)는 빨간색 톤으로 구분해 보여준다 - 둘 다 성공으로 보이지
 * 않게 하는 것이 목적이다.
 */

import { ApiClientError } from "@/lib/api-client";

export default function ErrorBanner({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const isApiError = error instanceof ApiClientError;
  const notImplemented = isApiError && error.code === "NOT_IMPLEMENTED";
  const message = isApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "알 수 없는 오류가 발생했습니다.";

  return (
    <div
      role="alert"
      className={`rounded-lg border p-4 text-sm ${
        notImplemented
          ? "border-[var(--color-warning)] bg-[var(--color-warning-bg)] text-[var(--color-warning)]"
          : "border-[var(--color-danger)] bg-[var(--color-danger-bg)] text-[var(--color-danger)]"
      }`}
    >
      <p className="font-semibold">
        {notImplemented ? "백엔드 API 미구현" : "요청을 처리하지 못했습니다"}
      </p>
      <p className="mt-1">{message}</p>
      {isApiError && (
        <p className="mt-1 text-xs opacity-80">
          코드: {error.code}
          {error.http_status ? ` · HTTP ${error.http_status}` : ""}
          {error.request_id ? ` · request_id: ${error.request_id}` : ""}
        </p>
      )}
      {notImplemented && (
        <p className="mt-2 text-xs opacity-90">
          TODO: 백엔드 관리자 승인 API(BACKEND-007) 구현 후 이 화면이 자동으로 정상 동작합니다.
        </p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="tap-target mt-3 rounded-md border border-current px-3 py-1.5 text-xs font-medium hover:opacity-80"
        >
          다시 시도
        </button>
      )}
    </div>
  );
}
