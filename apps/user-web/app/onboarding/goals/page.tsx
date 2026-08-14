"use client";

/**
 * U-04 방문 목적 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-04 방문 목적" 와이어프레임 텍스트("최대 3개",
 * 8개 선택지, 자유 입력, `[건너뛰기] [다음]`)와 "직접 입력은 LLM이 구조화하되 사용자가
 * 변환 결과를 다음 화면에서 확인·수정할 수 있어야 한다"는 설명.
 * API: 인터페이스 명세 8.1절 `PUT /api/v1/profiles/me/goals` (`postAnswers({step:"GOALS"})`).
 *
 * 코드값은 PUBLISHED 온톨로지의 VISIT_GOAL/BUSINESS_GOAL assignable concept를 사용한다.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, postAnswers, postInteraction } from "@/lib/api-client";
import {
  BUYER_GOAL_OPTIONS,
  canonicalizeLegacyProfileCode,
  VISITOR_GOAL_OPTIONS,
} from "@/lib/profile-options";
import type { SuggestedAttribute } from "@/lib/types";
import { loadOnboardingState, saveOnboardingState } from "@/lib/onboarding-state";

import ChoiceChip from "../_components/ChoiceChip";
import OnboardingShell from "../_components/OnboardingShell";

const MAX_GOALS = 3;

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function GoalsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [userType, setUserType] = useState<"GENERAL_VISITOR" | "BUYER" | null>(null);

  // 선택 순서를 유지해야 priority(1,2,3)를 매길 수 있다.
  const [selectedCodes, setSelectedCodes] = useState<string[]>([]);
  const [freeText, setFreeText] = useState("");
  const [suggestedAttributes, setSuggestedAttributes] = useState<SuggestedAttribute[]>([]);

  const [busy, setBusy] = useState<"next" | "skip" | "none">("none");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const state = loadOnboardingState();
    if (!state.guestSessionId) {
      router.replace("/start");
      return;
    }
    if (!state.privacyChoiceRecorded) {
      router.replace("/onboarding/privacy");
      return;
    }
    setUserType(state.userType);
    setSelectedCodes(state.goals.map((goal) => canonicalizeLegacyProfileCode(goal.code)));
    setFreeText(state.freeTextGoal);
    setReady(true);
  }, [router]);

  const nextRoute = useMemo(
    () => (userType === "BUYER" ? "/onboarding/buyer-needs" : "/onboarding/taste"),
    [userType],
  );
  const goalOptions = userType === "BUYER" ? BUYER_GOAL_OPTIONS : VISITOR_GOAL_OPTIONS;

  function toggleGoal(code: string) {
    setSelectedCodes((prev) => {
      if (prev.includes(code)) return prev.filter((item) => item !== code);
      if (prev.length >= MAX_GOALS) return prev;
      return [...prev, code];
    });
  }

  async function handleSkip() {
    setBusy("skip");
    void postInteraction({
      event_type: "PROFILE_QUESTION_SKIPPED",
      screen: "ONBOARDING_GOALS",
      occurred_at: new Date().toISOString(),
      context: { question: "visit_goals" },
    }).catch(() => {
      // 16.2절: 분석 이벤트 전송 실패가 온보딩 진행을 막지 않는다.
    });
    saveOnboardingState({ goalsCompleted: true });
    router.push(nextRoute);
  }

  async function handleNext() {
    setBusy("next");
    setErrorMessage(null);
    try {
      const visitGoals = selectedCodes.map((code, index) => ({ code, priority: index + 1 }));
      const response = await postAnswers({
        step: "GOALS",
        data: {
          visit_goals: visitGoals,
          free_text_goal: freeText.trim() ? freeText.trim() : null,
        },
      });
      setSuggestedAttributes(response.suggested_attributes);
      saveOnboardingState({
        goals: visitGoals,
        freeTextGoal: freeText.trim(),
        goalsCompleted: true,
        profileVersion: response.profile_version,
      });
      // 17절: LLM 구조화 결과는 사용자가 확인해야 하드 필터로 쓰인다. 결과가 있으면
      // 화면에 보여주고, 다음 화면 이동은 사용자의 확인(다시 "다음")을 기다린다.
      if (response.confirmation_required && response.suggested_attributes.length > 0) {
        setBusy("none");
        return;
      }
      router.push(nextRoute);
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
      setBusy("none");
    }
  }

  if (!ready) return null;

  return (
    <OnboardingShell title="오늘 무엇을 하고 싶나요?" stepLabel="3 / 5">
      <p className="-mt-3 text-sm" style={{ color: "var(--color-text-muted)" }}>
        최대 {MAX_GOALS}개
      </p>

      {errorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {goalOptions.map((option) => (
          <ChoiceChip
            key={option.code}
            label={option.label}
            selected={selectedCodes.includes(option.code)}
            onClick={() => toggleGoal(option.code)}
            disabled={!selectedCodes.includes(option.code) && selectedCodes.length >= MAX_GOALS}
          />
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="free-text-goal" className="text-sm font-bold">
          구체적인 목표가 있나요?
        </label>
        <input
          id="free-text-goal"
          type="text"
          value={freeText}
          onChange={(event) => setFreeText(event.target.value)}
          placeholder="예: 부모님 선물용 전통주를 찾고 있습니다."
          className="tap-target rounded-lg border px-3 py-2 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
        />
      </div>

      {suggestedAttributes.length > 0 ? (
        <div
          className="flex flex-col gap-2 rounded-lg border p-3"
          style={{ borderColor: "var(--color-border)" }}
          role="status"
        >
          <p className="text-sm font-bold">입력하신 내용에서 이렇게 이해했어요.</p>
          <ul className="flex flex-col gap-1">
            {suggestedAttributes.map((attribute, index) => (
              <li key={`${attribute.attribute}-${index}`} className="text-sm">
                “{attribute.evidence_text}” → {attribute.attribute}: {attribute.value}
              </li>
            ))}
          </ul>
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            내용이 맞으면 다음으로 진행해 주세요. 다르다면 위 입력을 수정할 수 있어요.
          </p>
          <button
            type="button"
            onClick={() => router.push(nextRoute)}
            className="tap-target self-start rounded-lg px-4 py-2 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            맞아요, 계속할게요
          </button>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={handleSkip}
          disabled={busy !== "none"}
          className="tap-target rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ color: "var(--color-text-muted)" }}
        >
          건너뛰기
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={busy !== "none"}
          className="tap-target flex-1 rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {busy === "next" ? "저장하는 중…" : "다음"}
        </button>
      </div>
    </OnboardingShell>
  );
}
