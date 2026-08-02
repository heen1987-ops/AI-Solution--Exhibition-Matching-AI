"use client";

/**
 * 화면 내장형 휴대전화 인증 위젯.
 *
 * 근거 문서
 * ---------
 * - docs/frontend-backend-ai-interface-spec.md 5절(권한·스코프) - "서버 저장·일정 |
 *   PHONE_VERIFIED", "상담 요청 | PHONE_VERIFIED + BUYER" 등 여러 화면(U-18, U-19, U-22)이
 *   휴대전화 인증을 요구한다. 7.2절 - OTP 요청·검증·세션 병합 흐름의 1차 근거.
 * - docs/user-ia-wireframes.md 1.1절 6번 원칙 - "회원가입을 진입 조건으로 강제하지 않는다.
 *   저장·상담 등 본인 연결이 필요한 시점에만 OTP 인증을 요구한다." - 별도 페이지로
 *   리다이렉트하지 않고 필요한 화면에 바로 내장하는 이유.
 *
 * 이 저장소에는 아직 전용 휴대전화 인증 라우트(U-01 영역, 이 작업 범위 밖)가 없어, U-18·U-19·
 * U-22 세 화면이 각자 인증을 요구할 때 이 위젯을 그대로 내장해 쓴다. `frontend/lib/api-client.ts`
 * 가 이미 정의한 `requestPhoneChallenge`/`verifyPhoneChallenge`/`mergeCurrentSession`만
 * 사용하고, 그 결과를 `frontend/lib/auth-state.ts`(로컬 힌트)와
 * `frontend/lib/local-favorites.ts`(관심목록 합치기)에 반영한다.
 */

import { useState, type FormEvent } from "react";

import {
  ApiClientError,
  mergeCurrentSession,
  requestPhoneChallenge,
  verifyPhoneChallenge,
} from "@/lib/api-client";
import {
  isAuthenticationState,
  setAuthState,
  type AuthenticationState,
} from "@/lib/auth-state";
import { mergeLocalFavoritesToServer } from "@/lib/local-favorites";

export interface InlinePhoneVerifyProps {
  title?: string;
  description?: string;
  onVerified?: (state: AuthenticationState) => void;
}

type Step = "phone" | "code" | "merge" | "done";

function extractErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) return error.message;
  return fallback;
}

export default function InlinePhoneVerify({
  title = "본인 인증이 필요해요",
  description = "휴대전화 번호로 간단히 인증하면 이 기기 밖에서도 정보를 안전하게 보관할 수 있어요.",
  onVerified,
}: InlinePhoneVerifyProps) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mergeNote, setMergeNote] = useState<string | null>(null);

  async function finishAndNotify(state: AuthenticationState) {
    // U-19 저장목록: 인증 시점에 로컬 저장 항목을 서버로 합친다 (작업 지시).
    try {
      const result = await mergeLocalFavoritesToServer();
      if (result.mergedCount > 0) {
        setMergeNote(`이 브라우저에 저장했던 관심목록 ${result.mergedCount}건을 계정에 합쳤어요.`);
      }
      if (result.failed.length > 0) {
        setMergeNote(
          (prev) =>
            `${prev ? `${prev} ` : ""}${result.failed.length}건은 합치지 못했어요. 관심목록 화면에서 다시 시도할 수 있어요.`,
        );
      }
    } catch {
      // 합치기 실패는 인증 자체의 실패가 아니므로 조용히 넘어간다 - 관심목록 화면에서 재시도 가능.
    }
    setStep("done");
    onVerified?.(state);
  }

  async function handleRequestChallenge(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const trimmed = phone.trim();
    if (!trimmed) {
      setError("휴대전화 번호를 입력해 주세요.");
      return;
    }
    setBusy(true);
    try {
      const response = await requestPhoneChallenge({ phone_number: trimmed });
      setChallengeId(response.challenge_id);
      setStep("code");
    } catch (err) {
      setError(extractErrorMessage(err, "인증번호 요청에 실패했습니다."));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyCode(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!challengeId) {
      setError("인증 요청 정보가 없습니다. 처음부터 다시 시도해 주세요.");
      setStep("phone");
      return;
    }
    const trimmed = code.trim();
    if (!trimmed) {
      setError("인증번호를 입력해 주세요.");
      return;
    }
    setBusy(true);
    try {
      const response = await verifyPhoneChallenge(challengeId, { code: trimmed });
      if (!response.verified) {
        setError("인증번호가 올바르지 않습니다. 다시 확인해 주세요.");
        return;
      }
      if (!isAuthenticationState(response.authentication_state)) {
        throw new Error("unknown authentication state");
      }
      setAuthState(response.authentication_state);
      if (response.authentication_state === "ACCOUNT_AUTHENTICATED") {
        await finishAndNotify(response.authentication_state);
      } else {
        // PHONE_VERIFIED만 된 상태 - 계정 병합 여부를 명시적으로 확인한다 (7.2절: "이미 다른
        // 계정에 연결된 데이터를 자동 병합하지 않는다").
        setStep("merge");
      }
    } catch (err) {
      setError(extractErrorMessage(err, "인증 확인에 실패했습니다."));
    } finally {
      setBusy(false);
    }
  }

  async function handleMergeChoice(confirmMerge: boolean) {
    setBusy(true);
    setError(null);
    try {
      if (confirmMerge) {
        const response = await mergeCurrentSession({ confirm_merge: true });
        setAuthState("ACCOUNT_AUTHENTICATED", response.user_id);
        await finishAndNotify("ACCOUNT_AUTHENTICATED");
      } else {
        await finishAndNotify("PHONE_VERIFIED");
      }
    } catch (err) {
      setError(extractErrorMessage(err, "계정 연결에 실패했습니다."));
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded-xl border p-4 text-sm"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        <p className="font-semibold" style={{ color: "var(--color-success)" }}>
          인증이 완료됐어요.
        </p>
        {mergeNote ? (
          <p className="mt-1" style={{ color: "var(--color-text-muted)" }}>
            {mergeNote}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      <h3 className="text-base font-bold">{title}</h3>
      <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
        {description}
      </p>

      {error ? (
        <p role="alert" className="mt-3 text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}

      {step === "phone" ? (
        <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={handleRequestChallenge}>
          <label className="sr-only" htmlFor="inline-phone-input">
            휴대전화 번호
          </label>
          <input
            id="inline-phone-input"
            type="tel"
            inputMode="numeric"
            autoComplete="tel"
            placeholder="휴대전화 번호 (예: 01012345678)"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            className="min-h-[44px] flex-1 rounded-lg border px-3 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <button
            type="submit"
            disabled={busy}
            className="tap-target rounded-lg px-4 font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            {busy ? "요청 중..." : "인증번호 받기"}
          </button>
        </form>
      ) : null}

      {step === "code" ? (
        <form className="mt-3 flex flex-col gap-2 sm:flex-row" onSubmit={handleVerifyCode}>
          <label className="sr-only" htmlFor="inline-code-input">
            인증번호
          </label>
          <input
            id="inline-code-input"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="인증번호 6자리"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            className="min-h-[44px] flex-1 rounded-lg border px-3 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <button
            type="submit"
            disabled={busy}
            className="tap-target rounded-lg px-4 font-semibold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            {busy ? "확인 중..." : "인증 확인"}
          </button>
          <button
            type="button"
            onClick={() => {
              setStep("phone");
              setCode("");
              setError(null);
            }}
            className="tap-target rounded-lg px-3 text-sm underline"
            style={{ color: "var(--color-text-muted)" }}
          >
            번호 다시 입력
          </button>
        </form>
      ) : null}

      {step === "merge" ? (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-sm">
            이 브라우저에 저장된 프로파일·관심목록을 계정에 합칠까요? 이미 다른 계정에 연결된
            정보는 자동으로 합쳐지지 않아요.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => handleMergeChoice(true)}
              className="tap-target rounded-lg px-4 font-semibold"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              합치기
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => handleMergeChoice(false)}
              className="tap-target rounded-lg border px-4 font-semibold"
              style={{ borderColor: "var(--color-border)" }}
            >
              나중에
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
