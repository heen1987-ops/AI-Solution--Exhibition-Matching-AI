"use client";

/**
 * U-08 행동 중심 추천 홈.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 5.1절: 경로 `/home`, 진입 조건 "최소 프로파일", 핵심 API
 *   `GET /recommendations` - 실제 계약은 인터페이스 명세 9.3절의 `GET /api/v1/home`이며
 *   `frontend/lib/api-client.ts`의 `getRecommendations()`(인자 없이 호출 시 홈으로 위임)를
 *   그대로 쓴다.
 * - 7절 U-08 와이어프레임: "지금 할 일"(부스·상담 건수 요약 + 추천 경로 시작),
 *   "지금 방문하면 좋은 부스"(추천 카드), "다음 일정"(확정 상담), "추천 조건 수정" 4개
 *   블록 구성의 1차 근거.
 * - 11.1절(추천 없음)/19절(오류 코드 표) - 빈 결과와 오류를 정상 상태로 다룬다. 절대조건은
 *   사용자 동의 없이 자동 완화하지 않으므로 "조건 완화해서 보기"는 링크 이동만 한다.
 * - 10절 - 카드 자체(`RecommendationCard`)가 지양 표현을 걸러내므로 이 화면은 요약 문구도
 *   실제 응답 개수 기반으로만 만든다(추정 시간·인원수를 지어내지 않는다).
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiClientError, getProfile, getRecommendations, listMeetings } from "@/lib/api-client";
import { parseLocalPersonalizationPreview } from "@/lib/personalization-preview";
import type { MeetingResponse, ProfileView, RecommendationResponse } from "@/lib/types";

import KakaoTestPreview from "@/components/KakaoTestPreview";
import LocalRecommendationCard from "@/components/LocalRecommendationCard";
import RecommendationCard from "@/components/RecommendationCard";
import OperatingStatusBadge from "@/components/OperatingStatusBadge";
import PersonalizationProof from "@/components/PersonalizationProof";

type LoadState = "loading" | "loaded" | "empty" | "error";

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ErrorGuidance({ error, onRetry }: { error: ApiClientError | null; onRetry: () => void }) {
  // 19절 오류 코드 표에 따라 화면 처리를 분기한다.
  if (error?.code === "AGE_CONFIRMATION_REQUIRED" || error?.code === "PROFILE_INCOMPLETE") {
    return (
      <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
        <p className="font-semibold">추천을 보려면 몇 가지 정보가 더 필요해요.</p>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          자격 확인과 최소 프로파일을 완료하면 맞춤 추천을 볼 수 있어요.
        </p>
        <Link
          href="/start"
          className="tap-target mt-3 inline-flex rounded-lg px-4 text-sm font-bold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          프로파일 이어하기
        </Link>
      </div>
    );
  }

  if (error?.code === "PERSONALIZATION_DISABLED") {
    return (
      <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
        <p className="font-semibold">개인화 추천에 동의하지 않으셨어요.</p>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          동의 없이도 부스·제품을 직접 둘러볼 수 있어요.
        </p>
        <Link
          href="/explore"
          className="tap-target mt-3 inline-flex rounded-lg border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          직접 탐색하기
        </Link>
      </div>
    );
  }

  if (error?.code === "RECOMMENDATION_NOT_READY") {
    return (
      <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
        <p className="font-semibold">나의 추천 업체를 준비하고 있어요.</p>
        <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
          추천 계산과 화면 전달은 분리되어 있어요. 준비가 끝나면 이 화면에서 바로 확인할 수 있습니다.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="tap-target rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            다시 확인
          </button>
          <Link
            href="/explore"
            className="tap-target rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            업체 직접 찾기
          </Link>
        </div>
      </div>
    );
  }

  const message =
    error?.code === "NETWORK_ERROR"
      ? "서버에 연결할 수 없어요. 네트워크 상태를 확인해 주세요."
      : (error?.message ?? "추천을 불러오지 못했어요.");

  return (
    <div role="alert" className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
      <p className="font-semibold" style={{ color: "var(--color-danger)" }}>
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="tap-target mt-3 rounded-lg border px-4 text-sm font-semibold"
        style={{ borderColor: "var(--color-border)" }}
      >
        다시 시도
      </button>
    </div>
  );
}

function EmptyRecommendations() {
  // 11.1절: 조건 완화·조건 수정·직접 탐색 3개 선택지를 제공하고, 절대조건을 자동으로
  // 완화하지 않는다(사용자 명시 이동만 한다).
  return (
    <div className="rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
      <p className="font-semibold">지금 조건에 정확히 맞는 추천이 아직 없어요.</p>
      <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
        조건을 조정하거나 직접 둘러보면 더 많은 결과를 볼 수 있어요.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href="/recommendations"
          className="tap-target rounded-lg border px-3 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          조건 완화해서 보기
        </Link>
        <Link
          href="/profile/preferences"
          className="tap-target rounded-lg border px-3 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          추천 조건 수정
        </Link>
        <Link
          href="/explore"
          className="tap-target rounded-lg border px-3 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          직접 탐색
        </Link>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1].map((key) => (
        <div key={key} className="animate-pulse rounded-2xl border p-4" style={{ borderColor: "var(--color-border)" }}>
          <div className="h-5 w-2/3 rounded" style={{ backgroundColor: "var(--color-border)" }} />
          <div className="mt-2 h-4 w-1/2 rounded" style={{ backgroundColor: "var(--color-border)" }} />
          <div className="mt-4 h-9 w-full rounded-lg" style={{ backgroundColor: "var(--color-border)" }} />
        </div>
      ))}
    </div>
  );
}

export default function MyEventDashboard() {
  const preview = useMemo(() => parseLocalPersonalizationPreview(), []);
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<RecommendationResponse | null>(null);
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);
  const [nextMeeting, setNextMeeting] = useState<MeetingResponse | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    if (preview) {
      setData(null);
      setProfile(null);
      setState(preview.recommendations.length > 0 ? "loaded" : "empty");
      return;
    }
    try {
      const [response, loadedProfile] = await Promise.all([
        getRecommendations(),
        getProfile().catch(() => null),
      ]);
      setData(response);
      setProfile(loadedProfile);
      setState(response.items.length === 0 ? "empty" : "loaded");
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "NO_CANDIDATE") {
        setData(null);
        setState("empty");
        return;
      }
      setError(err instanceof ApiClientError ? err : null);
      setState("error");
    }
  }, [preview]);

  useEffect(() => {
    void load();
  }, [load]);

  // U-08 "다음 일정" - 확정된 상담이 있으면 보여준다. 상담 조회 실패는 홈 전체를 막지
  // 않도록 조용히 섹션만 숨긴다(다른 블록은 정상 동작해야 하므로 - 1.1절 UX 원칙 7).
  useEffect(() => {
    if (preview) return;
    let cancelled = false;
    async function loadNextMeeting() {
      try {
        const page = await listMeetings({ status: "CONFIRMED", limit: 1 });
        if (!cancelled) setNextMeeting(page.items[0] ?? null);
      } catch {
        if (!cancelled) setNextMeeting(null);
      }
    }
    void loadNextMeeting();
    return () => {
      cancelled = true;
    };
  }, [preview]);

  const boothItems = data?.items.filter((item) => item.object_type === "BOOTH") ?? [];
  const visibleItems = (boothItems.length > 0 ? boothItems : (data?.items ?? [])).slice(0, 10);
  const meetingActionCount = data?.items.filter((item) => item.recommended_action === "REQUEST_MEETING").length ?? 0;
  const recommendationCount = preview?.recommendations.length ?? visibleItems.length;

  return (
    <div className="mx-auto max-w-screen-content space-y-7 px-4 py-4 md:space-y-10 md:py-7">
      <header className="backju-hero">
        <div className="backju-hero-content">
          <div className="backju-personal-panel">
            <p className="backju-eyebrow">AI PERSONAL MATCH</p>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight md:text-3xl">
              {preview ? `${preview.displayName} 님의 행사` : "나의 행사"}
            </h1>
            <p className="mt-1 max-w-xl text-sm text-white/90 md:text-base">
              {preview
                ? "사전등록 관심분야와 관람목적이 추천에 어떻게 반영됐는지 바로 확인하세요."
                : "관심 분야에 맞춘 업체와 오늘의 방문 동선을 확인하세요."}
            </p>
          </div>
        </div>
      </header>
      <p className="backju-asset-credit -mt-4 text-right">
        행사 이미지 출처: {" "}
        <a href="https://www.backju.kr/" target="_blank" rel="noreferrer">
          대한민국 백주대간 공식 홈페이지
        </a>
      </p>

      <PersonalizationProof preview={preview} profile={profile} recommendation={data} />

      <nav className="grid grid-cols-3 gap-2" aria-label="나의 행사 바로가기">
        <Link
          href="/recommendations"
          className="backju-shortcut tap-target px-3 py-3 text-center text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="backju-shortcut-label">추천 업체</span>
        </Link>
        <Link
          href="/saved"
          className="backju-shortcut tap-target px-3 py-3 text-center text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="backju-shortcut-label">관심 업체</span>
        </Link>
        <Link
          href="/schedule"
          className="backju-shortcut tap-target px-3 py-3 text-center text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="backju-shortcut-label">상담 일정</span>
        </Link>
      </nav>

      <section aria-labelledby="today-todo-heading" className="backju-panel backju-today-panel p-5 md:p-7">
        <h2 id="today-todo-heading" className="backju-section-title text-lg font-bold">
          지금 할 일
        </h2>
        {state === "loaded" ? (
          <p className="mt-1 text-sm text-white/80">
            추천 업체 {recommendationCount}곳
            {meetingActionCount > 0 ? ` · 상담 제안 ${meetingActionCount}건` : ""}
            {nextMeeting ? " · 확정 상담 1건" : ""}
          </p>
        ) : (
          <p className="mt-1 text-sm text-white/80">
            오늘의 추천을 준비하고 있어요.
          </p>
        )}
        {state === "loaded" && recommendationCount > 0 ? (
          <Link
            href={preview ? "#recommended-booths-heading" : "/route?source=recommendations"}
            className="tap-target mt-4 inline-flex rounded-full px-5 text-sm font-bold"
            style={{ backgroundColor: "#ffffff", color: "var(--color-brand)" }}
          >
            {preview ? "추천 결과 확인" : "추천 동선 확인"}
          </Link>
        ) : (
          <Link
            href="/recommendations"
            className="tap-target mt-4 inline-flex rounded-full px-5 text-sm font-bold"
            style={{ backgroundColor: "#ffffff", color: "var(--color-brand)" }}
          >
            추천 업체 확인
          </Link>
        )}
      </section>

      <section aria-labelledby="recommended-booths-heading" className="space-y-3">
        <h2 id="recommended-booths-heading" className="backju-section-title text-lg font-bold">
          {preview ? "내 기준으로 우선 확인할 참가업체" : "지금 방문하면 좋은 부스"}
        </h2>
        {preview ? (
          <p className="text-sm leading-6" style={{ color: "var(--color-text-muted)" }}>
            실제 참가업체 등록자료를 개인화 화면에 연결한 검수 결과입니다. 운영 매칭 엔진의 확정 Snapshot과 외부 발송은
            아직 실행하지 않았습니다.
          </p>
        ) : null}

        {state === "loading" ? <LoadingSkeleton /> : null}
        {state === "error" ? <ErrorGuidance error={error} onRetry={() => void load()} /> : null}
        {state === "empty" ? <EmptyRecommendations /> : null}
        {state === "loaded" && preview
          ? preview.recommendations.map((item, index) => (
              <LocalRecommendationCard
                key={`${item.exhibitorName}-${item.productName}`}
                item={item}
                rank={index + 1}
              />
            ))
          : null}
        {state === "loaded" && data
          ? visibleItems.map((item) => (
              <RecommendationCard
                key={`${item.object_type}-${item.object_id}-${item.rank}`}
                item={item}
                recommendationSessionId={data.recommendation_session_id}
                screen="HOME"
                stale={data.stale}
              />
            ))
          : null}

        {state === "loaded" && data && data.items.length > visibleItems.length ? (
          <Link
            href="/recommendations"
            className="tap-target inline-flex rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            추천 전체 보기
          </Link>
        ) : null}
      </section>

      {nextMeeting ? (
        <section aria-labelledby="next-schedule-heading" className="backju-panel border p-5" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
          <h2 id="next-schedule-heading" className="backju-section-title text-lg font-bold">
            다음 일정
          </h2>
          <div className="mt-2 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">
                {nextMeeting.confirmed_start ? formatDateTime(nextMeeting.confirmed_start) : "시간 조정 중"}
              </p>
              {nextMeeting.message_preview ? (
                <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                  {nextMeeting.message_preview}
                </p>
              ) : null}
            </div>
            <OperatingStatusBadge code="MEETING_CONFIRMED" size="sm" />
          </div>
          <Link
            href="/schedule"
            className="tap-target mt-3 inline-flex rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            일정 보기
          </Link>
        </section>
      ) : null}

      {preview ? <KakaoTestPreview preview={preview} /> : null}

      <div className="flex flex-wrap gap-2">
        <Link
          href="/profile/conversation"
          className="tap-target inline-flex rounded-lg px-4 text-sm font-bold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          대화로 조건 설정
        </Link>
        <Link
          href="/profile/preferences"
          className="tap-target inline-flex rounded-lg border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          직접 조건 수정
        </Link>
      </div>
    </div>
  );
}
