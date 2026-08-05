"use client";

/**
 * 상단 공통 영역.
 *
 * 근거: docs/user-ia-wireframes.md 4.2절(상단 공통 영역) - "행사 로고 또는 축약 행사명",
 * "선택한 방문일", "현재 구역과 `위치 갱신` 액션", "동기화 또는 네트워크 상태"의 1차 근거.
 * 같은 절이 "알림 진입점은 2차 확장", "추천 조건 수정은 홈·목록의 명시적 액션으로 제공"이라고
 * 명시하므로 이 컴포넌트에는 알림 아이콘과 추천 조건 수정 버튼을 넣지 않는다.
 *
 * 화면 에이전트 연동 메모: 이 컴포넌트는 상태를 직접 조회하지 않는다(세션·프로파일 상태
 * 관리는 이 작업 범위 밖). 방문일·구역 등은 상위 레이아웃/화면이 props로 내려주고, 값이
 * 없으면 "미설정" 플레이스홀더를 보여준다. 네트워크 온라인/오프라인만 이 컴포넌트가 직접
 * 감지해 `syncStatus`와 합성한다(11.4절 오프라인 배너 요구와 연결).
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export type SyncStatus = "synced" | "syncing" | "offline" | "error";

export interface TopBarProps {
  /** 행사 로고 이미지 대신 쓰는 축약 행사명. */
  eventName?: string;
  /** `YYYY-MM-DD`. 없으면 "방문일 미설정"을 보여준다. */
  visitDate?: string | null;
  /** 현재 구역 코드/명. 없으면 "구역 미확인"을 보여준다. */
  currentZone?: string | null;
  /** 구역 확인 방식과 시각을 함께 보여주기 위한 값 (13절 예시: "최근 QR: B구역 · 14:22"). */
  zoneObservedAt?: string | null;
  /** "위치 갱신" 액션. 지도에서 구역을 직접 선택하는 화면으로 이동하는 등 상위에서 정의한다. */
  onRefreshLocation?: () => void;
  /** 서버 동기화 상태. 생략하면 "synced"로 간주하고 브라우저 온라인 여부만 반영한다. */
  syncStatus?: SyncStatus;
}

function useIsOnline(): boolean {
  // SSR에서는 항상 온라인으로 가정하고, 마운트 후 실제 상태로 보정한다.
  const [isOnline, setIsOnline] = useState(true);

  useEffect(() => {
    setIsOnline(navigator.onLine);
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return isOnline;
}

function IconRefresh(props: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={20}
      height={20}
      aria-hidden="true"
      className={props.className}
    >
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  );
}

function IconCheck(props: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={16}
      height={16}
      aria-hidden="true"
      className={props.className}
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function IconOffline(props: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={16}
      height={16}
      aria-hidden="true"
      className={props.className}
    >
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
      <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
      <path d="M10.71 5.05A16 16 0 0 1 22.58 9" />
      <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
      <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
      <line x1="12" y1="20" x2="12.01" y2="20" />
    </svg>
  );
}

function IconWarning(props: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={16}
      height={16}
      aria-hidden="true"
      className={props.className}
    >
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

const SYNC_LABEL: Record<SyncStatus, string> = {
  synced: "동기화됨",
  syncing: "동기화 중",
  offline: "오프라인",
  error: "동기화 오류",
};

function SyncBadge({ status }: { status: SyncStatus }) {
  const color =
    status === "error"
      ? "var(--color-danger)"
      : status === "offline"
        ? "var(--color-text-muted)"
        : status === "syncing"
          ? "var(--color-brand)"
          : "var(--color-success)";

  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-medium"
      style={{ color }}
      role="status"
      aria-live="polite"
    >
      {status === "synced" && <IconCheck />}
      {status === "syncing" && <IconRefresh className="animate-spin" />}
      {status === "offline" && <IconOffline />}
      {status === "error" && <IconWarning />}
      <span>{SYNC_LABEL[status]}</span>
    </span>
  );
}

export default function TopBar({
  eventName = "2026 대한민국 백주대간",
  visitDate,
  currentZone,
  zoneObservedAt,
  onRefreshLocation,
  syncStatus = "synced",
}: TopBarProps) {
  const isOnline = useIsOnline();
  const pathname = usePathname();
  const effectiveStatus: SyncStatus = !isOnline ? "offline" : syncStatus;
  const isVenueDirections = pathname === "/map";

  return (
    <header
      role="banner"
      className="pt-safe-top fixed inset-x-0 top-0 z-40 border-b"
      style={{
        backgroundColor: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      <div className="topbar-shell mx-auto max-w-screen-content px-4">
        <div className="topbar-service-label" aria-hidden="true">
          <span>PERSONAL MATCHING</span>
          <strong>나의 행사</strong>
          {visitDate ? (
            <small style={{ color: "var(--color-text-muted)" }}>방문일 {visitDate}</small>
          ) : null}
        </div>

        <Link href="/home" className="topbar-official-link tap-target" title={eventName}>
          <span className="backju-brand-mark" aria-hidden="true" />
          <span className="sr-only">{eventName} 홈</span>
        </Link>

        <div className="topbar-status flex items-center gap-2 py-2">
          <div className="flex flex-col items-end text-xs" style={{ color: "var(--color-text-muted)" }}>
            <span className="text-sm font-medium" style={{ color: "var(--color-text)" }}>
              {isVenueDirections ? "EXCO 서관" : (currentZone ?? "구역 미확인")}
            </span>
            {zoneObservedAt ? <span>확인 {zoneObservedAt}</span> : null}
          </div>
          {!isVenueDirections ? (
            <button
              type="button"
              onClick={onRefreshLocation}
              className="tap-target rounded-full"
              style={{ color: "var(--color-brand)" }}
              aria-label="위치 갱신"
            >
              <IconRefresh />
            </button>
          ) : null}
          <SyncBadge status={effectiveStatus} />
        </div>
      </div>
    </header>
  );
}
