"use client";

/**
 * U-02 사용자 유형 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-02 사용자 유형" 와이어프레임 텍스트.
 * API: 인터페이스 명세 6절·7.3절 `PATCH /api/v1/profiles/me/user-type`
 * (`frontend/lib/api-client.ts`의 `patchProfileSession`).
 *
 * 6.1절 상태모델: `anonymous → role_selected`.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, patchProfileSession } from "@/lib/api-client";
import type { UserType } from "@/lib/types";
import { loadOnboardingState, saveOnboardingState } from "@/lib/onboarding-state";

import OnboardingShell from "../_components/OnboardingShell";

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function RolePage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [selecting, setSelecting] = useState<UserType | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    // 세션 없이 이 화면에 직접 들어온 경우 U-01로 되돌린다 (6.1절: 만료/미생성 세션 처리).
    const state = loadOnboardingState();
    if (!state.guestSessionId) {
      router.replace("/start");
      return;
    }
    setReady(true);
  }, [router]);

  async function handleSelect(userType: UserType) {
    setSelecting(userType);
    setErrorMessage(null);
    try {
      const response = await patchProfileSession({ user_type: userType });
      saveOnboardingState({
        userType,
        profileVersion: response.profile_version,
      });
      router.push("/onboarding/privacy");
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
    } finally {
      setSelecting(null);
    }
  }

  if (!ready) return null;

  return (
    <OnboardingShell title="어떤 목적으로 방문하시나요?" stepLabel="1 / 5" showBack={false}>
      {errorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <div className="flex flex-col gap-4">
        <button
          type="button"
          onClick={() => handleSelect("GENERAL_VISITOR")}
          disabled={selecting !== null}
          className="tap-target flex flex-col items-start gap-1 rounded-xl border-2 p-4 text-left disabled:cursor-not-allowed disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="text-lg font-bold">
            {selecting === "GENERAL_VISITOR" ? "선택하는 중… " : "일반 관람객"}
          </span>
          <span className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            시음 · 구매 · 체험
          </span>
        </button>

        <button
          type="button"
          onClick={() => handleSelect("BUYER")}
          disabled={selecting !== null}
          className="tap-target flex flex-col items-start gap-1 rounded-xl border-2 p-4 text-left disabled:cursor-not-allowed disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="text-lg font-bold">{selecting === "BUYER" ? "선택하는 중… " : "바이어·업계관계자"}</span>
          <span className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            거래처 · 제품 · 협력사 발굴
          </span>
        </button>
      </div>

      <p className="text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
        나중에 변경할 수 있어요.
      </p>
    </OnboardingShell>
  );
}
