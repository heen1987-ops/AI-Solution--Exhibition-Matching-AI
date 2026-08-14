"use client";

/**
 * U-03 자격·동의 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-03 자격·동의" 와이어프레임 텍스트와 설명
 * ("`만 19세 이상`은 입장 적격 확인이며 마케팅 동의가 아니다"), 6.1절 상태모델
 * (`role_selected → age_eligibility_confirmed → privacy_choice_recorded`, "개인화에
 * 동의하지 않으면 `general_browse`로 분기한다").
 * API: 인터페이스 명세 7.4절 `PUT /api/v1/consents/me` (`putConsents`).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, putConsents } from "@/lib/api-client";
import {
  CONSENT_DOCUMENT_VERSION,
  loadOnboardingState,
  saveOnboardingState,
} from "@/lib/onboarding-state";

import OnboardingShell from "../_components/OnboardingShell";

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

const PURPOSE_DETAILS: Record<string, string> = {
  age: "주류 정보 소개와 개인화 추천은 「청소년보호법」에 따라 성인 인증이 필요합니다.",
  personalization: "입력하신 관심·목적으로 맞춤 추천을 제공합니다. 동의하지 않아도 일반 검색·지도·행사정보는 그대로 이용할 수 있어요.",
  behavior: "부스 방문, 시음·구매 확인 같은 현장 QR 기록을 다음 추천에 반영해 더 정확하게 만들어요.",
  marketing: "행사 소식과 혜택 정보를 문자·알림으로 보내드려요.",
};

export default function PrivacyPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [personalization, setPersonalization] = useState(true);
  const [behavior, setBehavior] = useState(false);
  const [marketing, setMarketing] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  const [busy, setBusy] = useState<"continue" | "browse" | "none">("none");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const state = loadOnboardingState();
    if (!state.guestSessionId || !state.userType) {
      router.replace(state.guestSessionId ? "/onboarding/role" : "/start");
      return;
    }
    setReady(true);
  }, [router]);

  async function submitConsents(options: {
    age: boolean;
    personalized: boolean;
    behaviorPersonalization: boolean;
    marketingMessages: boolean;
  }) {
    return putConsents({
      consents: [
        {
          purpose: "AGE_CONFIRMATION",
          document_version: CONSENT_DOCUMENT_VERSION,
          accepted: options.age,
          source_channel: "WEB",
        },
        {
          purpose: "PERSONALIZED_RECOMMENDATION",
          document_version: CONSENT_DOCUMENT_VERSION,
          accepted: options.personalized,
          source_channel: "WEB",
        },
        {
          purpose: "BEHAVIOR_PERSONALIZATION",
          document_version: CONSENT_DOCUMENT_VERSION,
          accepted: options.behaviorPersonalization,
          source_channel: "WEB",
        },
        {
          purpose: "MARKETING_MESSAGES",
          document_version: CONSENT_DOCUMENT_VERSION,
          accepted: options.marketingMessages,
          source_channel: "WEB",
        },
      ],
    });
  }

  async function handleContinue() {
    if (!ageConfirmed) {
      setErrorMessage("만 19세 이상 확인은 필수예요.");
      return;
    }
    setBusy("continue");
    setErrorMessage(null);
    try {
      await submitConsents({
        age: true,
        personalized: personalization,
        behaviorPersonalization: behavior,
        marketingMessages: marketing,
      });
      saveOnboardingState({
        ageConfirmed: true,
        personalizationConsent: personalization,
        behaviorConsent: behavior,
        marketingConsent: marketing,
        privacyChoiceRecorded: true,
      });
      router.push(personalization ? "/onboarding/goals" : "/explore");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  async function handleBrowseWithoutPersonalization() {
    setBusy("browse");
    setErrorMessage(null);
    try {
      await submitConsents({
        age: ageConfirmed,
        personalized: false,
        behaviorPersonalization: false,
        marketingMessages: false,
      });
      saveOnboardingState({
        ageConfirmed,
        personalizationConsent: false,
        behaviorConsent: false,
        marketingConsent: false,
        privacyChoiceRecorded: true,
      });
      router.push("/explore");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  if (!ready) return null;

  const busyAny = busy !== "none";

  return (
    <OnboardingShell title="이용 전 확인" stepLabel="2 / 5">
      {errorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
          필수 확인
        </legend>
        <label className="tap-target flex items-start gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
          <input
            type="checkbox"
            checked={ageConfirmed}
            onChange={(event) => setAgeConfirmed(event.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-base">만 19세 이상입니다.</span>
        </label>
        {showDetails ? (
          <p className="px-3 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {PURPOSE_DETAILS.age}
          </p>
        ) : null}
      </fieldset>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
          개인화 서비스
        </legend>
        <label className="tap-target flex items-start gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
          <input
            type="checkbox"
            checked={personalization}
            onChange={(event) => setPersonalization(event.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-base">관심·목적을 이용한 맞춤추천</span>
        </label>
        {showDetails ? (
          <p className="px-3 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {PURPOSE_DETAILS.personalization}
          </p>
        ) : null}
      </fieldset>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-bold" style={{ color: "var(--color-text-muted)" }}>
          선택
        </legend>
        <label className="tap-target flex items-start gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
          <input
            type="checkbox"
            checked={behavior}
            onChange={(event) => setBehavior(event.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-base">QR 방문기록으로 추천 개선</span>
        </label>
        {showDetails ? (
          <p className="px-3 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {PURPOSE_DETAILS.behavior}
          </p>
        ) : null}
        <label className="tap-target flex items-start gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
          <input
            type="checkbox"
            checked={marketing}
            onChange={(event) => setMarketing(event.target.checked)}
            className="mt-1 h-5 w-5"
          />
          <span className="text-base">행사 소식·혜택 수신</span>
        </label>
        {showDetails ? (
          <p className="px-3 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {PURPOSE_DETAILS.marketing}
          </p>
        ) : null}
      </fieldset>

      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={handleContinue}
          disabled={busyAny}
          className="tap-target rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {busy === "continue" ? "저장하는 중…" : "선택 내용으로 계속"}
        </button>

        <button
          type="button"
          onClick={handleBrowseWithoutPersonalization}
          disabled={busyAny}
          className="tap-target text-sm font-semibold underline disabled:cursor-not-allowed disabled:opacity-60"
          style={{ color: "var(--color-text-muted)" }}
        >
          {busy === "browse" ? "이동하는 중…" : "개인화 없이 둘러보기"}
        </button>

        <button
          type="button"
          onClick={() => setShowDetails((prev) => !prev)}
          aria-expanded={showDetails}
          className="tap-target text-sm font-semibold underline"
          style={{ color: "var(--color-text-muted)" }}
        >
          {showDetails ? "항목별 자세히 보기 접기" : "항목별 자세히 보기"}
        </button>
      </div>
    </OnboardingShell>
  );
}
