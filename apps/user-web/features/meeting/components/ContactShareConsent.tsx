"use client";

/**
 * U-14 "수락 시 연락처를 공유합니다" 체크박스 + 공유 항목 상세.
 *
 * 절대 금지 사항(작업 지시): 이 체크박스는 항상 기본값 미체크(unchecked)로 시작해야 한다 -
 * 절대 미리 체크해두지 않는다. `checked` prop을 부모 상태에서 받아 그리기만 하고, 이 컴포넌트
 * 스스로 초기값을 true로 두지 않는 것으로 그 규칙을 지킨다.
 */

import { ALLOWED_CONTACT_SHARE_FIELDS, type ContactShareField } from "../types";
import { CONTACT_FIELD_LABEL } from "../constants";

export interface ContactShareConsentProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  selectedFields: ContactShareField[];
  onToggleField: (field: ContactShareField) => void;
  showDetail: boolean;
  onToggleDetail: () => void;
}

export default function ContactShareConsent({
  checked,
  onCheckedChange,
  selectedFields,
  onToggleField,
  showDetail,
  onToggleDetail,
}: ContactShareConsentProps) {
  return (
    <section aria-labelledby="share-heading" className="flex flex-col gap-2">
      <h2 id="share-heading" className="sr-only">
        연락처 공유
      </h2>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onCheckedChange(event.target.checked)}
          className="tap-target"
          aria-label="수락 시 연락처를 공유합니다"
        />
        수락 시 연락처를 공유합니다
      </label>
      <button
        type="button"
        onClick={onToggleDetail}
        className="self-start text-sm underline"
        style={{ color: "var(--color-brand)" }}
        aria-expanded={showDetail}
      >
        공유 항목 자세히 보기
      </button>
      {showDetail ? (
        <div
          className="flex flex-col gap-1 rounded-lg border p-3"
          style={{ borderColor: "var(--color-border)" }}
        >
          <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            업체가 상담을 수락한 뒤에만 아래에서 선택한 항목이 공개됩니다.
          </p>
          {ALLOWED_CONTACT_SHARE_FIELDS.map((field) => (
            <label key={field} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                disabled={!checked}
                checked={selectedFields.includes(field)}
                onChange={() => onToggleField(field)}
                className="tap-target"
              />
              {CONTACT_FIELD_LABEL[field]}
            </label>
          ))}
        </div>
      ) : null}
    </section>
  );
}
