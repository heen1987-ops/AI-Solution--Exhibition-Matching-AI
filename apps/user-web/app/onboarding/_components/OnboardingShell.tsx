"use client";

/**
 * 온보딩 화면(U-01~U-07) 공용 카드 레이아웃.
 *
 * 근거: docs/user-ia-wireframes.md 7절 각 와이어프레임이 공통으로 쓰는 단일 카드 박스
 * (`┌──…──┐`) 형태와 13.1절(모바일 360~430px, 카드 1열)을 그대로 구현한다. 15.1절
 * 완료 기준 "이전·건너뛰기·중간 이탈·재개가 동작한다"를 만족하기 위해 뒤로가기 액션과
 * 진행 단계 표시를 공통 헤더에 둔다.
 *
 * `frontend/app/layout.tsx`는 전역 상단바·하단탭을 항상 렌더링하므로(다른 에이전트 작업
 * 범위, 이 작업 지시에서 수정 금지 대상은 아니지만 공용 루트 파일이라 건드리지 않는다),
 * 이 컴포넌트는 그 안에서 목업이 보여주는 단일 카드를 재현하는 역할만 한다.
 */

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

export interface OnboardingShellProps {
  title: string;
  /** 예: "3 / 7". 생략하면 표시하지 않는다. */
  stepLabel?: string;
  /** 뒤로가기 버튼을 숨기려면 false (U-01 시작 화면). */
  showBack?: boolean;
  children: ReactNode;
}

export default function OnboardingShell({
  title,
  stepLabel,
  showBack = true,
  children,
}: OnboardingShellProps) {
  const router = useRouter();

  return (
    <div className="flex min-h-[calc(100dvh-var(--top-bar-height)-var(--bottom-nav-height)-var(--safe-top)-var(--safe-bottom))] justify-center px-4 py-6 sm:py-8">
      <div className="flex w-full max-w-[430px] flex-col">
        <div className="mb-3 flex items-center justify-between">
          {showBack ? (
            <button
              type="button"
              onClick={() => router.back()}
              className="tap-target -ml-2 inline-flex items-center gap-1 rounded-md px-2 text-sm font-medium"
              style={{ color: "var(--color-text-muted)" }}
              aria-label="이전 화면으로"
            >
              <span aria-hidden="true">←</span> 이전
            </button>
          ) : (
            <span />
          )}
          {stepLabel ? (
            <span className="text-xs font-medium" style={{ color: "var(--color-text-muted)" }}>
              {stepLabel}
            </span>
          ) : null}
        </div>

        <section
          className="flex flex-col gap-5 rounded-2xl border p-5 shadow-sm sm:p-6"
          style={{
            backgroundColor: "var(--color-surface)",
            borderColor: "var(--color-border)",
          }}
          aria-labelledby="onboarding-title"
        >
          <h1 id="onboarding-title" className="text-xl font-bold leading-snug">
            {title}
          </h1>
          {children}
        </section>
      </div>
    </div>
  );
}
