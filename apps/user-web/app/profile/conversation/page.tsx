"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  ApiClientError,
  decideConversationExtraction,
  getProfile,
  sendConversationMessage,
  startConversation,
} from "@/lib/api-client";
import type {
  ConversationClarification,
  ConversationExtraction,
  ConversationStartResponse,
  ExtractionDecisionResponse,
} from "@/lib/types";

type LoadState = "loading" | "ready" | "error";
type ProposalStatus = ConversationExtraction & {
  decision?: ExtractionDecisionResponse;
  decisionError?: string;
};
type ChatMessage = {
  id: string;
  role: "USER" | "ASSISTANT";
  text: string;
  proposals?: ProposalStatus[];
  nextQuestion?: ConversationClarification | null;
  recommendationReady?: boolean;
};

const REQUIREMENT_LABELS: Record<string, string> = {
  REQUIRED: "필수 조건",
  PREFERRED: "선호 조건",
  ACCEPTABLE: "허용 조건",
  EXCLUDED: "제외 조건",
};

function suggestionFor(userType: ConversationStartResponse["user_type"] | null): string[] {
  if (userType === "BUYER") {
    return [
      "서울 바틀샵에 증류주 200병 정도 납품할 업체를 찾고 있어요.",
      "MOQ 100병 이하로 정기 납품 가능한 업체를 찾고 있어요.",
    ];
  }
  return [
    "부모님 선물용으로 5만 원 이하의 드라이한 증류주를 찾고 있어요.",
    "시음할 수 있는 산뜻한 막걸리를 찾고 있어요.",
  ];
}

function formatValue(extraction: ConversationExtraction): string {
  const value = extraction.value;
  if (typeof value.max === "number") {
    return `${value.max.toLocaleString("ko-KR")}원 이하`;
  }
  if (typeof value.count === "number") {
    return `약 ${value.count.toLocaleString("ko-KR")}병`;
  }
  if (value.selected === true) {
    return extraction.requirement_level === "EXCLUDED" ? "추천에서 제외" : "추천에 반영";
  }
  return Object.values(value)
    .filter((item): item is string | number | boolean =>
      ["string", "number", "boolean"].includes(typeof item),
    )
    .map(String)
    .join(", ");
}

function decisionMessage(decision: ExtractionDecisionResponse): string {
  if (decision.status === "REJECTED") return "반영하지 않음";
  if (decision.application_status === "APPLIED") return "프로파일에 반영됨";
  if (decision.application_status === "STRUCTURED_FIELD_REQUIRED") {
    return "확인됨 · 거래조건 입력 단계에서 적용 예정";
  }
  return "확인됨";
}

export default function ConversationProfilePage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [conversation, setConversation] = useState<ConversationStartResponse | null>(null);
  const [profileVersion, setProfileVersion] = useState(1);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [decidingExtractionId, setDecidingExtractionId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const initialize = useCallback(async () => {
    setLoadState("loading");
    setErrorMessage(null);
    try {
      const [profile, started] = await Promise.all([
        getProfile(),
        startConversation({ language: "ko" }),
      ]);
      setConversation(started);
      setProfileVersion(profile.current_version);
      setMessages([
        {
          id: `welcome-${started.conversation_id}`,
          role: "ASSISTANT",
          text:
            started.user_type === "BUYER"
              ? "찾는 제품, 유통채널, 지역과 예상 수량을 편하게 말씀해 주세요. 이해한 조건은 적용 전에 하나씩 확인받겠습니다."
              : "찾는 술의 목적, 맛, 가격대를 편하게 말씀해 주세요. 이해한 조건은 적용 전에 하나씩 확인받겠습니다.",
        },
      ]);
      setLoadState("ready");
    } catch (error) {
      setErrorMessage(
        error instanceof ApiClientError ? error.message : "대화형 추천을 시작하지 못했습니다.",
      );
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  const submitMessage = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!conversation || !message || sending) return;

      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "USER",
        text: message,
      };
      setMessages((current) => [...current, userMessage]);
      setDraft("");
      setSending(true);
      setErrorMessage(null);

      try {
        const response = await sendConversationMessage(conversation.conversation_id, { message });
        setMessages((current) => [
          ...current,
          {
            id: `assistant-${response.message_id}`,
            role: "ASSISTANT",
            text: response.assistant_message,
            proposals: response.extractions,
            nextQuestion: response.next_question,
            recommendationReady: response.recommendation_ready,
          },
        ]);
      } catch (error) {
        setErrorMessage(
          error instanceof ApiClientError ? error.message : "메시지를 처리하지 못했습니다.",
        );
      } finally {
        setSending(false);
      }
    },
    [conversation, sending],
  );

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage(draft);
  }

  async function decide(extractionId: string, action: "CONFIRM" | "REJECT") {
    if (!conversation || decidingExtractionId) return;
    setDecidingExtractionId(extractionId);
    setErrorMessage(null);

    try {
      const response = await decideConversationExtraction(
        conversation.conversation_id,
        extractionId,
        { action, expected_profile_version: profileVersion },
      );
      setProfileVersion(response.profile_version);
      setMessages((current) =>
        current.map((message) => ({
          ...message,
          proposals: message.proposals?.map((proposal) =>
            proposal.extraction_id === extractionId
              ? { ...proposal, status: response.status, decision: response, decisionError: undefined }
              : proposal,
          ),
        })),
      );
    } catch (error) {
      const message =
        error instanceof ApiClientError && error.http_status === 409
          ? "다른 화면에서 조건이 변경됐습니다. 새로고침 후 다시 확인해 주세요."
          : error instanceof ApiClientError
            ? error.message
            : "조건을 처리하지 못했습니다.";
      setMessages((current) =>
        current.map((chatMessage) => ({
          ...chatMessage,
          proposals: chatMessage.proposals?.map((proposal) =>
            proposal.extraction_id === extractionId
              ? { ...proposal, decisionError: message }
              : proposal,
          ),
        })),
      );
    } finally {
      setDecidingExtractionId(null);
    }
  }

  if (loadState === "loading") {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-8" role="status" aria-live="polite">
        <div className="rounded-2xl border p-5" style={{ borderColor: "var(--color-border)" }}>
          대화형 추천을 준비하고 있어요.
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-8">
        <div className="rounded-2xl border p-5" style={{ borderColor: "var(--color-border)" }}>
          <h1 className="text-lg font-bold">대화를 시작하지 못했어요.</h1>
          <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {errorMessage}
          </p>
          <button
            type="button"
            onClick={() => void initialize()}
            className="tap-target mt-4 rounded-lg px-4 text-sm font-bold"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            다시 시도
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <p className="text-sm font-semibold" style={{ color: "var(--color-brand)" }}>
          대화로 추천 조건 설정
        </p>
        <h1 className="mt-1 text-2xl font-bold">원하는 조건을 말해 주세요</h1>
        <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
          전화번호와 이메일은 저장 전에 가려집니다. 추출한 조건은 확인을 눌러야 추천에
          반영됩니다.
        </p>
      </header>

      <section aria-label="대화 내용" className="flex flex-col gap-3" aria-live="polite">
        {messages.map((message) => (
          <article
            key={message.id}
            className={`max-w-[92%] rounded-2xl border p-4 ${
              message.role === "USER" ? "ml-auto" : "mr-auto"
            }`}
            style={{
              borderColor:
                message.role === "USER" ? "var(--color-brand)" : "var(--color-border)",
              backgroundColor:
                message.role === "USER" ? "var(--color-brand)" : "var(--color-surface)",
              color:
                message.role === "USER" ? "var(--color-brand-contrast)" : "var(--color-text)",
            }}
          >
            <p className="whitespace-pre-wrap">{message.text}</p>

            {message.proposals && message.proposals.length > 0 ? (
              <div className="mt-4 space-y-3">
                {message.proposals.map((proposal) => {
                  const decided = Boolean(proposal.decision);
                  const busy = decidingExtractionId === proposal.extraction_id;
                  return (
                    <div
                      key={proposal.extraction_id}
                      className="rounded-xl border p-3"
                      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="text-xs font-semibold" style={{ color: "var(--color-text-muted)" }}>
                            {REQUIREMENT_LABELS[proposal.requirement_level] ?? "추천 조건"}
                          </p>
                          <p className="mt-1 font-bold">{proposal.source_text}</p>
                          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
                            {formatValue(proposal)} · {proposal.attribute_code}
                          </p>
                        </div>
                        {proposal.decision ? (
                          <span
                            className="rounded-full px-2 py-1 text-xs font-bold"
                            style={{ color: "var(--color-success)" }}
                          >
                            {decisionMessage(proposal.decision)}
                          </span>
                        ) : null}
                      </div>

                      {!decided ? (
                        <div className="mt-3 flex gap-2">
                          <button
                            type="button"
                            disabled={decidingExtractionId !== null}
                            onClick={() => void decide(proposal.extraction_id, "CONFIRM")}
                            className="tap-target flex-1 rounded-lg px-3 text-sm font-bold disabled:opacity-50"
                            style={{
                              backgroundColor: "var(--color-brand)",
                              color: "var(--color-brand-contrast)",
                            }}
                          >
                            {busy ? "처리 중" : "이 조건 확인"}
                          </button>
                          <button
                            type="button"
                            disabled={decidingExtractionId !== null}
                            onClick={() => void decide(proposal.extraction_id, "REJECT")}
                            className="tap-target rounded-lg border px-3 text-sm font-semibold disabled:opacity-50"
                            style={{ borderColor: "var(--color-border)" }}
                          >
                            반영 안 함
                          </button>
                        </div>
                      ) : null}
                      {proposal.decisionError ? (
                        <p className="mt-2 text-sm" role="alert" style={{ color: "var(--color-danger)" }}>
                          {proposal.decisionError}
                        </p>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : null}

            {message.nextQuestion ? (
              <div className="mt-4">
                <p className="text-sm font-semibold">{message.nextQuestion.text}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {message.nextQuestion.options.map((option) => (
                    <button
                      key={option}
                      type="button"
                      disabled={sending}
                      onClick={() => void submitMessage(option)}
                      className="tap-target rounded-full border px-3 text-sm font-semibold disabled:opacity-50"
                      style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {message.recommendationReady &&
            (!message.proposals ||
              message.proposals.length === 0 ||
              message.proposals.every((proposal) => proposal.decision?.status === "CONFIRMED")) ? (
              <Link
                href="/recommendations"
                className="tap-target mt-4 w-full rounded-lg px-4 text-sm font-bold"
                style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
              >
                확인한 조건으로 추천 보기
              </Link>
            ) : null}
          </article>
        ))}
        {sending ? (
          <p className="text-sm" role="status" style={{ color: "var(--color-text-muted)" }}>
            입력한 조건을 확인하고 있어요.
          </p>
        ) : null}
      </section>

      {messages.length === 1 ? (
        <section aria-label="입력 예시">
          <p className="text-sm font-semibold">이렇게 시작해 보세요</p>
          <div className="mt-2 flex flex-col gap-2">
            {suggestionFor(conversation?.user_type ?? null).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={sending}
                onClick={() => void submitMessage(suggestion)}
                className="min-h-11 rounded-xl border p-3 text-left text-sm disabled:opacity-50"
                style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {errorMessage ? (
        <p role="alert" className="rounded-xl border p-3 text-sm" style={{ borderColor: "var(--color-danger)", color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <form onSubmit={handleSubmit} className="rounded-2xl border p-3" style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}>
        <label htmlFor="conversation-message" className="sr-only">
          원하는 추천 조건
        </label>
        <textarea
          id="conversation-message"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          maxLength={2000}
          disabled={sending}
          placeholder="예: 5만 원 이하의 드라이한 증류주를 찾고 있어요"
          className="w-full resize-none bg-transparent p-1"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            {draft.length}/2,000
          </span>
          <button
            type="submit"
            disabled={sending || draft.trim().length === 0}
            className="tap-target rounded-lg px-5 text-sm font-bold disabled:opacity-50"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            조건 보내기
          </button>
        </div>
      </form>

      <Link href="/profile/preferences" className="mx-auto text-sm underline" style={{ color: "var(--color-text-muted)" }}>
        선택형 화면에서 직접 수정
      </Link>
    </div>
  );
}
