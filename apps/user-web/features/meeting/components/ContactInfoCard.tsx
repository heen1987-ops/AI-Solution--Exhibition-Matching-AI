"use client";

/**
 * 확정(accepted) 상담에서만 노출되는 업체 담당자 연락처 카드.
 *
 * 절대 규칙(작업 지시): 확정 이전에는 렌더링하지 않는다. 확정 상태라도 API가 아직 연락처
 * 필드를 채워주지 않았다면(현재 백엔드 계약의 알려진 gap, `types.ts`의 `MeetingResponse.contact`
 * 주석 참고) "비어 보이는 깨진 placeholder" 대신 그냥 아무것도 그리지 않는다 - 그래서 이
 * 컴포넌트는 `shouldShowContactCard`를 통과하지 못하면 `null`을 반환한다.
 */

import { EXHIBITOR_CONTACT_FIELD_LABEL } from "../constants";
import { shouldShowContactCard } from "../logic";
import type { MeetingResponse } from "../types";

function formatDateTime(iso: string | null): string {
  if (!iso) return "미정";
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export interface ContactInfoCardProps {
  meeting: MeetingResponse;
}

export default function ContactInfoCard({ meeting }: ContactInfoCardProps) {
  if (!shouldShowContactCard(meeting)) return null;
  const contact = meeting.contact as Record<string, string>;

  return (
    <section aria-labelledby="contact-heading" className="flex flex-col gap-2">
      <h2 id="contact-heading" className="text-base font-semibold">
        업체 담당자 연락처
      </h2>
      <dl
        className="flex flex-col gap-2 rounded-lg border p-4 text-sm"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
      >
        {Object.entries(contact).map(([key, value]) => {
          if (!value) return null;
          const label = EXHIBITOR_CONTACT_FIELD_LABEL[key] ?? key;
          return (
            <div key={key} className="flex justify-between gap-4">
              <dt style={{ color: "var(--color-text-muted)" }}>{label}</dt>
              <dd className="text-right font-medium">{value}</dd>
            </div>
          );
        })}
        <div className="flex justify-between gap-4">
          <dt style={{ color: "var(--color-text-muted)" }}>상담 시간</dt>
          <dd className="text-right font-medium">
            {formatDateTime(meeting.confirmed_start)} ~ {formatDateTime(meeting.confirmed_end)}
          </dd>
        </div>
      </dl>
    </section>
  );
}
