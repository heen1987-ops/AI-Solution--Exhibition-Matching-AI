/**
 * 이벤트 메시지 API 함수.
 *
 * `apps/admin/lib/api-client.ts`(apiGet/apiPost/apiPatch, X-Actor-User-Id 세션 자동첨부,
 * 표준화된 ApiClientError)를 그대로 재사용한다(그 파일 자체는 소유 경로 밖이라 수정하지
 * 않는다 - `../ai-review/api.ts`/`../no-result-operations/api.ts`와 동일 관례).
 *
 * 경로 근거
 * ---------
 * `apps/api/app/api/v1/routers/event_message.py`(이 트랙이 이번 배치에서 함께 구현)가
 * `build_event_message_router()`를 노출한다. 그 모듈 docstring이 제안하는 mount 방식대로
 * `/admin` 프리픽스를 가정해 아래 경로를 구성했다 - `app/api/v1/api.py`(통합 담당자 소유)에
 * 실제로 등록되기 전까지는 모든 호출이 FastAPI 전역 404 → `ApiClientError(code:
 * "NOT_IMPLEMENTED")`로 실패한다(`ErrorBanner`가 이를 있는 그대로 보여준다).
 */

import { apiGet, apiPatch, apiPost, type RequestOptions } from "@/lib/api-client";

import type {
  EventMessage,
  EventMessageCreateRequest,
  EventMessageListResponse,
  EventMessagePreview,
  EventMessageUpdateRequest,
  MessageStatus,
  PublishResult,
  Uuid,
} from "./types";

const BASE = "/admin/event-messages";

export function listEventMessages(
  eventId: Uuid,
  status?: MessageStatus,
  options?: RequestOptions,
): Promise<EventMessageListResponse> {
  return apiGet<EventMessageListResponse>(BASE, {
    ...options,
    query: { event_id: eventId, status },
  });
}

export function getEventMessage(
  eventMessageId: Uuid,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiGet<EventMessage>(`${BASE}/${encodeURIComponent(eventMessageId)}`, options);
}

export function createEventMessage(
  body: EventMessageCreateRequest,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPost<EventMessage>(BASE, body, options);
}

export function updateEventMessage(
  eventMessageId: Uuid,
  body: EventMessageUpdateRequest,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPatch<EventMessage>(`${BASE}/${encodeURIComponent(eventMessageId)}`, body, options);
}

export function previewEventMessage(
  eventMessageId: Uuid,
  options?: RequestOptions,
): Promise<EventMessagePreview> {
  return apiPost<EventMessagePreview>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/preview`,
    undefined,
    options,
  );
}

export function approveEventMessage(
  eventMessageId: Uuid,
  rowVersion: number,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPost<EventMessage>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/approve`,
    { row_version: rowVersion },
    options,
  );
}

export function scheduleEventMessage(
  eventMessageId: Uuid,
  rowVersion: number,
  scheduledAt: string,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPost<EventMessage>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/schedule`,
    { row_version: rowVersion, scheduled_at: scheduledAt },
    options,
  );
}

export function publishEventMessage(
  eventMessageId: Uuid,
  rowVersion: number,
  options?: RequestOptions,
): Promise<PublishResult> {
  return apiPost<PublishResult>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/publish`,
    { row_version: rowVersion },
    options,
  );
}

/** 작업 지시에는 명시되지 않았지만 상태머신에 필요한 안전한 되돌리기 동작(취소) - 사유
 * 필수(백엔드 EventMessageCancelRequest.reason과 동일 규칙). */
export function cancelEventMessage(
  eventMessageId: Uuid,
  rowVersion: number,
  reason: string,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPost<EventMessage>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/cancel`,
    { row_version: rowVersion, reason },
    options,
  );
}

export function completeEventMessage(
  eventMessageId: Uuid,
  rowVersion: number,
  options?: RequestOptions,
): Promise<EventMessage> {
  return apiPost<EventMessage>(
    `${BASE}/${encodeURIComponent(eventMessageId)}/complete`,
    { row_version: rowVersion },
    options,
  );
}
