"use client";

/**
 * U-22 MY·동의관리.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md
 *     5.1절 라우트 표: `/my/privacy`, 핵심 API `GET/PATCH /consents`(실제 경로는 인터페이스
 *     명세 7.4절 `GET/PUT /consents/me` - `frontend/lib/api-client.ts`의
 *     `getConsents`/`putConsents`), 진입조건 "인증".
 *     U-22절: "추천 프로파일과 조건 / 관심목록, 방문·상담 이력 / 개인화·행동정보·마케팅·
 *     연락처 공유 동의 / 개인정보 열람·다운로드 요청 / 프로파일 초기화 / 계정 연결 해제·탈퇴·
 *     삭제 요청. 동의 철회 결과를 즉시 설명한다."
 * - 작업 지시: "동의 목적별 상태와 철회, 프로파일 초기화, 삭제요청 UI(개인화, 행동정보,
 *   마케팅, 연락처공유 동의를 각각 별도 토글로)."
 *
 * 권한 경계에 대한 메모 (중요)
 * ------------------------------
 * `backend/app/api/v1/routers/consent.py`를 실제로 읽어보면 두 구역의 인증 요구 수준이
 * 다르다:
 *   - `/consents/me`(GET/PUT)는 게스트 세션만으로도 동작한다(주체가 `user_id` 또는
 *     `guest_session_id` 중 하나면 됨) - 그래서 이 화면의 동의 토글 4개는 인증 전에도
 *     보여주고 조작할 수 있게 한다.
 *   - `/privacy-requests`(열람·다운로드·초기화·삭제 요청)는 `subject.user_id`가 있어야
 *     하므로 휴대전화 인증만으로는 부족하고 계정 연결(`ACCOUNT_AUTHENTICATED`)까지 필요하다
 *     - 이 구역만 별도로 인증 유도 UI로 감싼다.
 *
 * "연락처 공유" 동의 코드에 대한 메모
 * ------------------------------------
 * `ConsentPurpose`(frontend/lib/types.ts)는 `AGE_CONFIRMATION` /
 * `PERSONALIZED_RECOMMENDATION` / `BEHAVIOR_PERSONALIZATION` / `MARKETING_MESSAGES` 4개만
 * 알려진 값으로 나열하고 나머지는 열린 문자열이다(`OpenEnum`). 와이어프레임 U-03/U-14는
 * "연락처 공유 동의는 상담 요청 화면에서 맥락에 맞게 별도로 받는다"고 적어 전역 목적 코드로
 * 세팅돼 있지 않을 수 있다. 이 화면은 작업 지시대로 `CONTACT_SHARE`를 네 번째 토글로
 * 노출하되, 아직 `consent_policy`에 해당 목적이 등록돼 있지 않으면(백엔드가
 * `VALIDATION_FAILED`로 응답) 그 메시지를 토글 아래에 그대로 보여주고 되돌린다 - 실제 정책이
 * 나중에 등록되면 별도 프론트 변경 없이 그대로 동작한다.
 *
 * "프로파일 초기화"에 대한 메모
 * -------------------------------
 * 즉시 초기화 전용 API가 아직 없어(작업 지시: "6~30단계 중 아직 설계 안 된 부분은 합리적
 * 기본값과 TODO로 남긴다") `POST /privacy-requests`에 `request_type: "CORRECT"`,
 * `scope: {action: "RESET_PROFILE"}`로 접수해 운영자가 처리하도록 한다.
 * TODO(전용 프로파일 초기화 API 도입 시): 즉시 처리되는 별도 엔드포인트로 교체한다.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import InlinePhoneVerify from "@/components/InlinePhoneVerify";
import {
  ApiClientError,
  createPrivacyRequest,
  getConsents,
  listPrivacyRequests,
  mergeCurrentSession,
  putConsents,
} from "@/lib/api-client";
import { getAuthState, setAuthState, subscribeAuthState } from "@/lib/auth-state";
import type { ConsentPurpose, ConsentStateItem, PrivacyRequestType, PrivacyRequestView } from "@/lib/types";

interface ConsentPurposeConfig {
  purpose: ConsentPurpose;
  label: string;
  description: string;
  offExplanation: string;
}

const CONSENT_PURPOSES: ConsentPurposeConfig[] = [
  {
    purpose: "PERSONALIZED_RECOMMENDATION",
    label: "개인화 추천",
    description: "관심·목적을 이용한 맞춤 추천을 받아요.",
    offExplanation: "끄면 맞춤 추천 대신 일반 탐색·지도만 이용할 수 있어요.",
  },
  {
    purpose: "BEHAVIOR_PERSONALIZATION",
    label: "행동정보 활용",
    description: "QR 방문기록 등 행동정보로 추천을 개선해요.",
    offExplanation:
      "앞으로 발생하는 행동은 개인화에 사용하지 않아요. 이미 모은 데이터의 처리·삭제 범위는 아래 삭제 요청에서 확인할 수 있어요.",
  },
  {
    purpose: "MARKETING_MESSAGES",
    label: "마케팅 메시지 수신",
    description: "행사 소식·혜택 알림을 받아요.",
    offExplanation: "앞으로 마케팅 메시지를 보내지 않아요.",
  },
  {
    // TODO(전역 CONTACT_SHARE 동의 정책 등록): 상단 파일 주석 참고.
    purpose: "CONTACT_SHARE",
    label: "연락처 공유",
    description: "상담을 수락한 업체에 연락처 공개를 허용해요.",
    offExplanation: "앞으로 상담 요청 시 화면에서 건별로 다시 확인해요.",
  },
];

const PRIVACY_ACTIONS: Array<{ type: PrivacyRequestType; label: string; description: string; destructive?: boolean }> = [
  { type: "ACCESS", label: "개인정보 열람 요청", description: "보관 중인 내 정보를 확인해요." },
  { type: "EXPORT", label: "다운로드 요청", description: "내 정보를 파일로 내려받아요." },
  { type: "CORRECT", label: "프로파일 초기화", description: "추천 프로파일 답변을 처음부터 다시 시작해요.", destructive: true },
  { type: "DELETE", label: "삭제 요청", description: "계정과 개인정보 삭제를 요청해요.", destructive: true },
  { type: "WITHDRAW", label: "전체 동의 철회", description: "모든 개인화·마케팅 동의를 한 번에 철회해요." },
];

const PRIVACY_STATUS_LABEL: Record<string, string> = {
  RECEIVED: "접수됨",
  VERIFYING: "본인확인 중",
  PROCESSING: "처리 중",
  COMPLETED: "완료",
  REJECTED: "거절됨",
};

function formatDate(iso: string | null): string {
  if (!iso) return "안내 예정";
  return new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
}

export default function MyPrivacyPage() {
  const [authState, setLocalAuthState] = useState(() => getAuthState().state);

  const [consents, setConsents] = useState<Map<string, ConsentStateItem>>(new Map());
  const [consentsLoadState, setConsentsLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [consentsError, setConsentsError] = useState<string | null>(null);
  const [pendingPurpose, setPendingPurpose] = useState<string | null>(null);
  const [purposeErrors, setPurposeErrors] = useState<Record<string, string>>({});
  const [purposeNotices, setPurposeNotices] = useState<Record<string, string>>({});

  const [linkingAccount, setLinkingAccount] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const [privacyRequests, setPrivacyRequests] = useState<PrivacyRequestView[]>([]);
  const [privacyLoadState, setPrivacyLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [privacyActionBusy, setPrivacyActionBusy] = useState<PrivacyRequestType | null>(null);
  const [privacyActionMessage, setPrivacyActionMessage] = useState<string | null>(null);

  useEffect(() => subscribeAuthState(() => setLocalAuthState(getAuthState().state)), []);

  const loadConsents = useCallback(async () => {
    setConsentsLoadState("loading");
    setConsentsError(null);
    try {
      const response = await getConsents();
      const map = new Map<string, ConsentStateItem>();
      for (const item of response.consents) map.set(item.purpose, item);
      setConsents(map);
      setConsentsLoadState("loaded");
    } catch (err) {
      setConsentsLoadState("error");
      setConsentsError(err instanceof ApiClientError ? err.message : "동의 상태를 불러오지 못했습니다.");
    }
  }, []);

  const loadPrivacyRequests = useCallback(async () => {
    setPrivacyLoadState("loading");
    try {
      const response = await listPrivacyRequests({ limit: 20 });
      setPrivacyRequests(response.items);
      setPrivacyLoadState("loaded");
    } catch {
      setPrivacyLoadState("error");
    }
  }, []);

  useEffect(() => {
    loadConsents();
  }, [loadConsents]);

  useEffect(() => {
    if (authState === "ACCOUNT_AUTHENTICATED") loadPrivacyRequests();
  }, [authState, loadPrivacyRequests]);

  async function handleToggle(config: ConsentPurposeConfig, nextAccepted: boolean) {
    setPendingPurpose(config.purpose);
    setPurposeErrors((prev) => ({ ...prev, [config.purpose]: "" }));
    const existing = consents.get(config.purpose);
    const documentVersion = existing?.document_version ?? "v1";
    try {
      const response = await putConsents({
        consents: [
          {
            purpose: config.purpose,
            document_version: documentVersion,
            accepted: nextAccepted,
            source_channel: "WEB",
          },
        ],
      });
      const updated = response.consents.find((item) => item.purpose === config.purpose);
      if (updated) {
        setConsents((prev) => new Map(prev).set(config.purpose, updated));
      }
      setPurposeNotices((prev) => {
        const next = { ...prev };
        if (!nextAccepted) next[config.purpose] = config.offExplanation;
        else delete next[config.purpose];
        return next;
      });
    } catch (err) {
      setPurposeErrors((prev) => ({
        ...prev,
        [config.purpose]: err instanceof ApiClientError ? err.message : "저장하지 못했습니다.",
      }));
    } finally {
      setPendingPurpose(null);
    }
  }

  async function handleLinkAccount() {
    setLinkingAccount(true);
    setLinkError(null);
    try {
      const response = await mergeCurrentSession({ confirm_merge: true });
      setAuthState("ACCOUNT_AUTHENTICATED", response.user_id);
    } catch (err) {
      setLinkError(err instanceof ApiClientError ? err.message : "계정 연결에 실패했습니다.");
    } finally {
      setLinkingAccount(false);
    }
  }

  async function handlePrivacyAction(action: (typeof PRIVACY_ACTIONS)[number]) {
    if (action.destructive) {
      const confirmed = window.confirm(`${action.label}을(를) 진행할까요? 이 작업은 운영팀이 접수 후 처리해요.`);
      if (!confirmed) return;
    }
    setPrivacyActionBusy(action.type);
    setPrivacyActionMessage(null);
    try {
      const scope =
        action.type === "CORRECT"
          ? { action: "RESET_PROFILE" }
          : action.type === "WITHDRAW"
            ? { scope: "ALL_CONSENTS" }
            : null;
      const response = await createPrivacyRequest({ request_type: action.type, scope });
      setPrivacyActionMessage(`${action.label} 접수됐어요. 처리기한 ${formatDate(response.due_at)}.`);
      loadPrivacyRequests();
    } catch (err) {
      setPrivacyActionMessage(err instanceof ApiClientError ? err.message : "요청을 접수하지 못했습니다.");
    } finally {
      setPrivacyActionBusy(null);
    }
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-xl font-bold">MY · 동의관리</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          동의 상태를 확인하고 언제든 철회할 수 있어요.
        </p>
      </header>

      <nav className="flex flex-wrap gap-2 text-sm">
        <Link
          href="/profile/preferences"
          className="tap-target rounded-lg border px-3"
          style={{ borderColor: "var(--color-border)" }}
        >
          추천 조건 수정 바로가기
        </Link>
        <Link href="/saved" className="tap-target rounded-lg border px-3" style={{ borderColor: "var(--color-border)" }}>
          관심목록 바로가기
        </Link>
        <Link href="/schedule" className="tap-target rounded-lg border px-3" style={{ borderColor: "var(--color-border)" }}>
          일정 바로가기
        </Link>
      </nav>

      <section
        className="flex flex-col gap-3 rounded-xl border p-4"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        <h2 className="text-base font-bold">동의 목적별 상태</h2>

        {consentsLoadState === "loading" ? (
          <p role="status" aria-live="polite" className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            불러오는 중이에요...
          </p>
        ) : null}
        {consentsLoadState === "error" ? (
          <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
            {consentsError}
          </p>
        ) : null}

        {consentsLoadState === "loaded"
          ? CONSENT_PURPOSES.map((config) => {
              const state = consents.get(config.purpose);
              const accepted = state?.accepted ?? false;
              const busy = pendingPurpose === config.purpose;
              return (
                <div key={config.purpose} className="border-t pt-3 first:border-t-0 first:pt-0" style={{ borderColor: "var(--color-border)" }}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">{config.label}</p>
                      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                        {config.description}
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={accepted}
                      aria-label={config.label}
                      disabled={busy}
                      onClick={() => handleToggle(config, !accepted)}
                      className="tap-target rounded-full px-3 text-sm font-semibold"
                      style={{
                        backgroundColor: accepted ? "var(--color-success)" : "var(--color-border)",
                        color: accepted ? "#fff" : "var(--color-text)",
                      }}
                    >
                      {busy ? "처리 중" : accepted ? "동의함" : "미동의"}
                    </button>
                  </div>
                  {purposeNotices[config.purpose] ? (
                    <p role="status" className="mt-1 text-xs" style={{ color: "var(--color-text-muted)" }}>
                      {purposeNotices[config.purpose]}
                    </p>
                  ) : null}
                  {purposeErrors[config.purpose] ? (
                    <p role="alert" className="mt-1 text-xs" style={{ color: "var(--color-danger)" }}>
                      {purposeErrors[config.purpose]}
                    </p>
                  ) : null}
                </div>
              );
            })
          : null}
      </section>

      <section
        className="flex flex-col gap-3 rounded-xl border p-4"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        <h2 className="text-base font-bold">개인정보 열람·초기화·삭제</h2>

        {authState !== "ACCOUNT_AUTHENTICATED" ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
              이 기능은 계정 연결 후 이용할 수 있어요.
            </p>
            {authState === "PHONE_VERIFIED" ? (
              <>
                <button
                  type="button"
                  disabled={linkingAccount}
                  onClick={handleLinkAccount}
                  className="tap-target rounded-lg px-4 text-sm font-semibold"
                  style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
                >
                  {linkingAccount ? "연결 중..." : "계정에 연결하기"}
                </button>
                {linkError ? (
                  <p role="alert" className="text-xs" style={{ color: "var(--color-danger)" }}>
                    {linkError}
                  </p>
                ) : null}
              </>
            ) : (
              <InlinePhoneVerify
                title="계정 연결이 필요해요"
                description="휴대전화 인증 후 계정에 연결하면 개인정보 열람·초기화·삭제를 요청할 수 있어요."
                onVerified={() => {
                  /* PHONE_VERIFIED로만 끝났다면 위 "계정에 연결하기" 버튼이 이어서 보인다. */
                }}
              />
            )}
          </div>
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-2">
              {PRIVACY_ACTIONS.map((action) => (
                <button
                  key={action.type}
                  type="button"
                  disabled={privacyActionBusy !== null}
                  onClick={() => handlePrivacyAction(action)}
                  className="tap-target rounded-lg border p-3 text-left"
                  style={{
                    borderColor: action.destructive ? "var(--color-danger)" : "var(--color-border)",
                  }}
                >
                  <span className="block text-sm font-semibold" style={{ color: action.destructive ? "var(--color-danger)" : "var(--color-text)" }}>
                    {privacyActionBusy === action.type ? "처리 중..." : action.label}
                  </span>
                  <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                    {action.description}
                  </span>
                </button>
              ))}
            </div>

            {privacyActionMessage ? (
              <p role="status" aria-live="polite" className="text-sm font-medium" style={{ color: "var(--color-success)" }}>
                {privacyActionMessage}
              </p>
            ) : null}

            <h3 className="mt-2 text-sm font-bold">요청 이력</h3>
            {privacyLoadState === "loading" ? (
              <p role="status" className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                불러오는 중이에요...
              </p>
            ) : null}
            {privacyLoadState === "error" ? (
              <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
                요청 이력을 불러오지 못했습니다.
              </p>
            ) : null}
            {privacyLoadState === "loaded" && privacyRequests.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                접수한 요청이 없어요.
              </p>
            ) : null}
            {privacyLoadState === "loaded" && privacyRequests.length > 0 ? (
              <ul className="flex flex-col gap-2">
                {privacyRequests.map((request) => (
                  <li
                    key={request.privacy_request_id}
                    className="rounded-lg border p-2 text-sm"
                    style={{ borderColor: "var(--color-border)" }}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">
                        {PRIVACY_ACTIONS.find((action) => action.type === request.request_type)?.label ??
                          request.request_type}
                      </span>
                      <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                        {PRIVACY_STATUS_LABEL[request.status] ?? request.status}
                      </span>
                    </div>
                    <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                      접수 {formatDate(request.requested_at)} · 처리기한 {formatDate(request.due_at)}
                      {request.completed_at ? ` · 완료 ${formatDate(request.completed_at)}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}
