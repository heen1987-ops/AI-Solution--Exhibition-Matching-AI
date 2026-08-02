"use client";

/**
 * U-01 시작 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-01 시작" 와이어프레임 텍스트와 동작 설명.
 * - `AI 추천 시작하기`: 익명 프로파일 세션 생성 (`POST /sessions`, 인터페이스 명세 7.1절).
 * - `사전등록 정보 불러오기`: 서명 링크 확인 또는 휴대전화 OTP. 이 저장소는 아직 서명 링크
 *   검증 엔드포인트가 없어(7.2절 프로즈만 있고 링크형 검증 API는 명세에 없음) 휴대전화 OTP
 *   경로만 실제로 구현한다. OTP 검증 성공 후 세션을 만들고 다음 단계(U-02)로 보낸다.
 * - `로그인 없이 둘러보기`: 개인화 온보딩 없이 일반 탐색으로 보낸다 (`/explore`, 4.1절).
 *
 * 6.1절 상태모델의 시작점(`anonymous`)에 해당한다.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiClientError,
  createProfileSession,
  mergeCurrentSession,
  requestPhoneChallenge,
  verifyPhoneChallenge,
} from "@/lib/api-client";
import { EVENT_ID, saveOnboardingState } from "@/lib/onboarding-state";

type BusyAction = "none" | "start" | "browse" | "otp-request" | "otp-verify";
type PrefillStep = "closed" | "phone" | "code";

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function StartPage() {
  const router = useRouter();
  const [busy, setBusy] = useState<BusyAction>("none");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [prefillStep, setPrefillStep] = useState<PrefillStep>("closed");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [otpNotice, setOtpNotice] = useState<string | null>(null);

  async function startAnonymousSession() {
    const response = await createProfileSession({
      event_id: EVENT_ID,
      entry_channel: "WEB",
      device_type: "MOBILE_WEB",
      language: "ko-KR",
    });
    saveOnboardingState({
      guestSessionId: response.guest_session_id,
      visitSessionId: response.visit_session_id,
      profileId: response.profile_id,
      minimumAge: response.minimum_age,
      eventStatus: response.event_status,
    });
    return response;
  }

  async function handleStart() {
    setBusy("start");
    setErrorMessage(null);
    try {
      const session = await startAnonymousSession();
      if (!session.service_available) {
        setErrorMessage("지금은 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      router.push("/onboarding/role");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  async function handleBrowseWithoutLogin() {
    setBusy("browse");
    setErrorMessage(null);
    try {
      await startAnonymousSession();
      router.push("/explore");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  async function handleRequestOtp() {
    if (!phoneNumber.trim()) {
      setErrorMessage("휴대전화 번호를 입력해 주세요.");
      return;
    }
    setBusy("otp-request");
    setErrorMessage(null);
    try {
      const response = await requestPhoneChallenge({ phone_number: phoneNumber.trim() });
      setChallengeId(response.challenge_id);
      setPrefillStep("code");
      setOtpNotice("인증번호를 문자로 보냈어요. 확인 후 아래에 입력해 주세요.");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  async function handleVerifyOtp() {
    if (!challengeId) {
      setErrorMessage("인증번호를 먼저 요청해 주세요.");
      setPrefillStep("phone");
      return;
    }
    if (!otpCode.trim()) {
      setErrorMessage("인증번호를 입력해 주세요.");
      return;
    }
    setBusy("otp-verify");
    setErrorMessage(null);
    try {
      const verifyResult = await verifyPhoneChallenge(challengeId, { code: otpCode.trim() });
      if (!verifyResult.verified) {
        setErrorMessage("인증번호가 올바르지 않습니다. 다시 확인해 주세요.");
        return;
      }
      // 사전등록 세션이 아직 없으면 익명 세션을 먼저 만든 뒤, 인증된 사용자로 데이터를
      // 합칠지 서버에 명시적으로 확인한다 (7.2절: "자동 병합하지 않는다").
      await startAnonymousSession();
      try {
        await mergeCurrentSession({ confirm_merge: true });
      } catch {
        // 합칠 기존 데이터가 없거나 병합이 불필요한 경우도 있으므로, 병합 실패만으로
        // 온보딩 진행을 막지 않는다.
      }
      router.push("/onboarding/role");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setBusy("none");
    }
  }

  const isStartDisabled = busy !== "none";

  return (
    <div className="flex min-h-[calc(100dvh-var(--top-bar-height)-var(--bottom-nav-height)-var(--safe-top)-var(--safe-bottom))] items-center justify-center px-4 py-8">
      <div
        className="flex w-full max-w-[430px] flex-col gap-6 rounded-2xl border p-6 text-center shadow-sm"
        style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <div>
          <p className="text-sm font-medium" style={{ color: "var(--color-text-muted)" }}>
            2026 대한민국 백주대간
          </p>
          <h1 className="mt-1 text-2xl font-extrabold">백주 AI 셀파</h1>
        </div>

        <div className="flex flex-col gap-1">
          <p className="text-base leading-relaxed">
            나에게 맞는 술·양조장과
            <br />
            상담할 업체를 찾아드려요.
          </p>
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            약 1분 · 앱 설치 없음
          </p>
        </div>

        {errorMessage ? (
          <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
            {errorMessage}
          </p>
        ) : null}

        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={handleStart}
            disabled={isStartDisabled}
            className="tap-target rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            {busy === "start" ? "시작하는 중…" : "AI 추천 시작하기"}
          </button>

          <button
            type="button"
            onClick={() => {
              setErrorMessage(null);
              setPrefillStep((prev) => (prev === "closed" ? "phone" : "closed"));
            }}
            disabled={busy === "start" || busy === "browse"}
            className="tap-target rounded-xl border px-4 py-3 text-base font-semibold disabled:cursor-not-allowed disabled:opacity-60"
            style={{ borderColor: "var(--color-border)" }}
            aria-expanded={prefillStep !== "closed"}
          >
            사전등록 정보 불러오기
          </button>

          {prefillStep !== "closed" ? (
            <div
              className="flex flex-col gap-3 rounded-xl border p-4 text-left"
              style={{ borderColor: "var(--color-border)" }}
            >
              {prefillStep === "phone" ? (
                <>
                  <label htmlFor="phone-number" className="text-sm font-semibold">
                    휴대전화 번호
                  </label>
                  <input
                    id="phone-number"
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel"
                    placeholder="01012345678"
                    value={phoneNumber}
                    onChange={(event) => setPhoneNumber(event.target.value)}
                    className="tap-target rounded-lg border px-3 py-2 text-base"
                    style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
                  />
                  <button
                    type="button"
                    onClick={handleRequestOtp}
                    disabled={busy === "otp-request"}
                    className="tap-target rounded-lg px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-60"
                    style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
                  >
                    {busy === "otp-request" ? "인증번호 요청 중…" : "인증번호 받기"}
                  </button>
                </>
              ) : (
                <>
                  {otpNotice ? (
                    <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                      {otpNotice}
                    </p>
                  ) : null}
                  <label htmlFor="otp-code" className="text-sm font-semibold">
                    인증번호
                  </label>
                  <input
                    id="otp-code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    placeholder="6자리 숫자"
                    value={otpCode}
                    onChange={(event) => setOtpCode(event.target.value)}
                    className="tap-target rounded-lg border px-3 py-2 text-base"
                    style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
                  />
                  <button
                    type="button"
                    onClick={handleVerifyOtp}
                    disabled={busy === "otp-verify"}
                    className="tap-target rounded-lg px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-60"
                    style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
                  >
                    {busy === "otp-verify" ? "확인하는 중…" : "인증하고 불러오기"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setPrefillStep("phone");
                      setOtpNotice(null);
                    }}
                    className="tap-target text-sm font-medium underline"
                    style={{ color: "var(--color-text-muted)" }}
                  >
                    번호 다시 입력
                  </button>
                </>
              )}
            </div>
          ) : null}
        </div>

        <button
          type="button"
          onClick={handleBrowseWithoutLogin}
          disabled={busy !== "none"}
          className="tap-target text-sm font-semibold underline disabled:cursor-not-allowed disabled:opacity-60"
          style={{ color: "var(--color-text-muted)" }}
        >
          {busy === "browse" ? "이동하는 중…" : "로그인 없이 둘러보기"}
        </button>
      </div>
    </div>
  );
}
