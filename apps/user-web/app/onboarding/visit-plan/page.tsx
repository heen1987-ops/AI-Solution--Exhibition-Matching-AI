"use client";

/**
 * U-07 방문 계획 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-07 방문 계획" 와이어프레임 텍스트(머무를 시간,
 * 우선순위, 상담 가능한 시간, `[추천 결과 보기]`). API: 인터페이스 명세 8.4절
 * `PUT /api/v1/visit-sessions/current/plan` (`postAnswers({step:"VISIT_PLAN"})`).
 *
 * 6.1절 상태모델의 마지막 단계(`minimum_profile_completed → recommendation_ready`)에
 * 해당한다 - 제출 성공 시 U-08 홈(`/home`, 이 작업 범위 밖)으로 보낸다.
 *
 * 시간대 메모: 인터페이스 명세 8.4절 예시가 `+09:00`(KST) 오프셋을 쓰므로 상담 가능 시간
 * 슬롯도 동일하게 구성한다.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, postAnswers } from "@/lib/api-client";
import type { MeetingSlotWindow, VisitPlanRequest } from "@/lib/types";
import { loadOnboardingState, saveOnboardingState, todayIsoDate } from "@/lib/onboarding-state";

import ChoiceChip from "../_components/ChoiceChip";
import OnboardingShell from "../_components/OnboardingShell";

type DurationOption = "30M" | "1H" | "2H" | "FLEXIBLE";
const DURATION_OPTIONS: { code: DurationOption; label: string; minutes: number | null }[] = [
  { code: "30M", label: "30분", minutes: 30 },
  { code: "1H", label: "1시간", minutes: 60 },
  { code: "2H", label: "2시간", minutes: 120 },
  { code: "FLEXIBLE", label: "여유", minutes: null },
];

const ROUTE_PREFERENCE_OPTIONS: {
  code: NonNullable<VisitPlanRequest["route_preference"]>;
  label: string;
}[] = [
  { code: "SHORTEST", label: "가까운 곳" },
  { code: "RECOMMENDED_FIRST", label: "추천 우선" },
  { code: "LOW_CONGESTION", label: "혼잡 적은 곳" },
];

const MEETING_SLOT_OPTIONS: { code: string; label: string; start: string; end: string }[] = [
  { code: "MORNING", label: "오전 (09:00~12:00)", start: "09:00", end: "12:00" },
  { code: "EARLY_AFTERNOON", label: "오후 (12:00~14:00)", start: "12:00", end: "14:00" },
  { code: "LATE_AFTERNOON", label: "오후 (14:00~17:00)", start: "14:00", end: "17:00" },
  { code: "EVENING", label: "저녁 (17:00~19:00)", start: "17:00", end: "19:00" },
];

function toKstIso(date: string, time: string): string {
  return `${date}T${time}:00+09:00`;
}

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function VisitPlanPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const [visitDate, setVisitDate] = useState(todayIsoDate());
  const [duration, setDuration] = useState<DurationOption | null>(null);
  const [routePreference, setRoutePreference] = useState<VisitPlanRequest["route_preference"] | null>(null);
  const [accessibleRoute, setAccessibleRoute] = useState(false);
  const [selectedSlots, setSelectedSlots] = useState<string[]>([]);

  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const state = loadOnboardingState();
    if (!state.guestSessionId) {
      router.replace("/start");
      return;
    }
    if (!state.minimumProfileCompleted && !state.goalsCompleted) {
      router.replace("/onboarding/goals");
      return;
    }
    if (state.visitDate) setVisitDate(state.visitDate);
    setReady(true);
  }, [router]);

  function toggleSlot(code: string) {
    setSelectedSlots((prev) => (prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]));
  }

  async function handleSubmit() {
    setBusy(true);
    setErrorMessage(null);
    try {
      const durationOption = DURATION_OPTIONS.find((option) => option.code === duration) ?? null;
      const meetingAvailableSlots: MeetingSlotWindow[] = MEETING_SLOT_OPTIONS.filter((slot) =>
        selectedSlots.includes(slot.code),
      ).map((slot) => ({
        start: toKstIso(visitDate, slot.start),
        end: toKstIso(visitDate, slot.end),
      }));

      const response = await postAnswers({
        step: "VISIT_PLAN",
        data: {
          visit_date: visitDate,
          available_minutes: durationOption?.minutes ?? null,
          route_preference: routePreference ?? null,
          walking_constraints: {
            minimize_distance: routePreference === "SHORTEST",
            accessible_route: accessibleRoute,
          },
          meeting_available_slots: meetingAvailableSlots,
        },
      });

      saveOnboardingState({
        visitDate: response.visit_date,
        minimumProfileCompleted: true,
      });
      router.push("/home");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  if (!ready) return null;

  return (
    <OnboardingShell title="오늘 방문 계획" stepLabel="5 / 5">
      {errorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <label htmlFor="visit-date" className="text-sm font-bold">
          방문일
        </label>
        <input
          id="visit-date"
          type="date"
          value={visitDate}
          onChange={(event) => setVisitDate(event.target.value)}
          className="tap-target w-full rounded-lg border px-3 py-2 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
        />
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">머무를 시간</h2>
        <div className="flex flex-wrap gap-2">
          {DURATION_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={duration === option.code}
              onClick={() => setDuration(option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">무엇을 우선할까요?</h2>
        <div className="flex flex-wrap gap-2">
          {ROUTE_PREFERENCE_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={routePreference === option.code}
              onClick={() => setRoutePreference(option.code)}
            />
          ))}
        </div>
        <label className="tap-target flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={accessibleRoute}
            onChange={(event) => setAccessibleRoute(event.target.checked)}
            className="h-5 w-5"
          />
          이동이 편한 경로를 우선해 주세요.
        </label>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">상담 가능한 시간</h2>
        <div className="flex flex-wrap gap-2">
          {MEETING_SLOT_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={selectedSlots.includes(option.code)}
              onClick={() => toggleSlot(option.code)}
            />
          ))}
        </div>
      </div>

      <button
        type="button"
        onClick={handleSubmit}
        disabled={busy}
        className="tap-target rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        {busy ? "추천을 준비하는 중…" : "추천 결과 보기"}
      </button>
    </OnboardingShell>
  );
}
