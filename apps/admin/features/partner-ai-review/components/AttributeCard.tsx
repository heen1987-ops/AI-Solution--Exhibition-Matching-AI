"use client";

/**
 * AI 제안 속성 1건 카드 - confirm/modify/delete 동작 + UNKNOWN->YES 명시적 확인 단계.
 * `app/partner/ai-review/[documentId]/page.tsx`에서 분리해 세션/라우팅 없이 단위 테스트할 수
 * 있게 했다(`../tests/AttributeCard.test.tsx` 참고).
 *
 * 2026-08-03 재조정: BACKEND-EXTRACTION 라우터가 착지한 실제 계약(`ExtractedAttributeRead`)에
 * 맞춰 다시 썼다 - 이전 버전은 라우터 착지 전 잠정 계약(`attribute_id`, `value_type`,
 * `current_value`, 단일 `evidence` 객체, `PENDING/CONFIRMED/MODIFIED/DELETED` 상태값)을
 * 대상으로 했다. `../types.ts` 모듈 docstring 참고.
 *
 * value_type 판별자 없음에 대한 메모: 실제 스키마에는 (구 잠정계약에 있던) 필드 값 종류
 * 판별자가 없다. 능력치(SUPPORTED/NOT_SUPPORTED/UNKNOWN) 필드는
 * `CAPABILITY_ENUM_ATTRIBUTE_CODES`로 식별하고, 숫자 필드는 알려진 코드 목록으로 식별한다
 * (아래 `NUMERIC_ATTRIBUTE_CODES` - 스키마가 명시적 타입을 노출하면 이 휴리스틱을 걷어내야
 * 한다, 보고서에 플래그).
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import { confirmProposedValue, rejectProposedValue, saveModifiedValue } from "../api";
import { confidenceLabel, confidenceTone, requiresExplicitUnknownToYesConfirmation } from "../logic";
import {
  ATTRIBUTE_LABEL_KO,
  CAPABILITY_ENUM_ATTRIBUTE_CODES,
  CAPABILITY_VALUES,
  CAPABILITY_VALUE_LABEL_KO,
  REVIEW_STATUS_LABEL_KO,
  VISIBILITY_LABEL_KO,
} from "../types";
import type { ExtractedAttributeRead, JsonValue } from "../types";

/** 스키마에 없는 휴리스틱(모듈 docstring 참고) - 숫자 입력으로 편집해야 하는 코드. */
const NUMERIC_ATTRIBUTE_CODES = new Set([
  "trade.moq",
  "trade.lead_time_days",
  "company.established_year",
  "product.abv_percent",
  "product.price_krw",
  "product.package_size_ml",
]);

function isCapabilityAttribute(attributeCode: string): boolean {
  return (CAPABILITY_ENUM_ATTRIBUTE_CODES as readonly string[]).includes(attributeCode);
}

export function formatDisplayValue(value: JsonValue): string {
  if (value === null || value === undefined || value === "") return "(값 없음)";
  if (typeof value === "string" && value in CAPABILITY_VALUE_LABEL_KO) {
    return CAPABILITY_VALUE_LABEL_KO[value];
  }
  if (Array.isArray(value)) return value.map((item) => formatDisplayValue(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function draftValueToString(value: JsonValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function AttributeCard({
  attribute,
  emphasized,
  onChange,
}: {
  attribute: ExtractedAttributeRead;
  emphasized: boolean;
  onChange: (updated: ExtractedAttributeRead) => void;
}) {
  const [busy, setBusy] = useState<"confirm" | "modify" | "delete" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [draftValue, setDraftValue] = useState<string>(
    draftValueToString(attribute.normalized_value ?? attribute.proposed_value),
  );
  const [justification, setJustification] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const isCapability = isCapabilityAttribute(attribute.attribute_code);
  const isNumeric = NUMERIC_ATTRIBUTE_CODES.has(attribute.attribute_code);
  const isTaxonomyRef = !isCapability && attribute.concept_codes !== null && attribute.concept_codes.length > 0;

  const tone = confidenceTone(attribute.confidence);
  const toneColor =
    tone === "low"
      ? "text-[var(--color-danger)]"
      : tone === "medium"
        ? "text-[var(--color-warning)]"
        : tone === "high"
          ? "text-[var(--color-success)]"
          : "text-[var(--color-text-muted)]";

  // UNKNOWN->YES 가드는 "수정(modify)" 경로에만 적용된다 - 순수 확인(confirm)은 이미 행에 있는
  // 값을 그대로 확정할 뿐이라 값 자체가 바뀌지 않는다(`../logic.ts`, `../api.ts` 모듈 docstring
  // 참고). "AI 제안값 확인" 버튼에는 그래서 게이트 패널이 없다.
  const wouldModifyBeUnknownToYes = requiresExplicitUnknownToYesConfirmation(attribute, draftValue);

  const decided = attribute.review_status !== "PROPOSED";

  const runConfirm = async () => {
    setBusy("confirm");
    setError(null);
    try {
      const updated = await confirmProposedValue(attribute, undefined);
      onChange(updated);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const runModify = async () => {
    setBusy("modify");
    setError(null);
    try {
      const updated = await saveModifiedValue(attribute, draftValue, {
        justification: wouldModifyBeUnknownToYes ? justification : undefined,
      });
      onChange(updated);
      setEditing(false);
      setJustification("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const runDelete = async () => {
    setBusy("delete");
    setError(null);
    try {
      const updated = await rejectProposedValue(attribute.extraction_id, deleteReason || undefined);
      onChange(updated);
      setShowDeleteConfirm(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className={`rounded-lg border p-4 ${
        emphasized ? "border-[var(--color-brand)]" : "border-[var(--color-border)]"
      } bg-[var(--color-surface)]`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">
            {ATTRIBUTE_LABEL_KO[attribute.attribute_code] ?? attribute.attribute_code}
          </p>
          <p className="font-mono text-xs text-[var(--color-text-muted)]">
            온톨로지 코드: {attribute.attribute_code}
            {attribute.concept_codes && attribute.concept_codes.length > 0
              ? ` (${attribute.concept_codes.join(", ")})`
              : ""}
          </p>
        </div>
        <span className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-2 py-0.5 text-xs">
          {REVIEW_STATUS_LABEL_KO[attribute.review_status] ?? attribute.review_status}
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-2 text-sm md:grid-cols-2">
        <div>
          <dt className="text-xs text-[var(--color-text-muted)]">AI 제안값</dt>
          <dd className="font-medium">{formatDisplayValue(attribute.proposed_value)}</dd>
        </div>
        <div>
          <dt className="text-xs text-[var(--color-text-muted)]">공개범위</dt>
          <dd>
            {attribute.visibility
              ? (VISIBILITY_LABEL_KO[attribute.visibility] ?? attribute.visibility)
              : "미지정"}
          </dd>
        </div>
      </dl>

      <p className={`mt-2 text-xs ${toneColor}`} role="status">
        {confidenceLabel(attribute.confidence)}
      </p>

      {attribute.evidence.length > 0 ? (
        <div className="mt-2 flex flex-col gap-2">
          {attribute.evidence.map((evidence) => (
            <div
              key={evidence.evidence_id}
              className="rounded-md bg-[var(--color-surface-muted)] p-2 text-xs italic text-[var(--color-text-muted)]"
            >
              <p>&ldquo;{evidence.evidence_text}&rdquo;</p>
              <p className="mt-1 not-italic">
                {evidence.page_number ? `${evidence.page_number}페이지` : "페이지 정보 없음"}
                {evidence.section_title ? ` · ${evidence.section_title}` : ""}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--color-danger)]">근거 문장이 제공되지 않았습니다.</p>
      )}

      {error ? <ErrorBanner error={error} /> : null}

      {!decided && !editing && !showDeleteConfirm && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void runConfirm()}
            disabled={busy !== null}
            className="tap-target rounded-md bg-[var(--color-success)] px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
          >
            {busy === "confirm" ? "확인 처리 중…" : "AI 제안값 확인"}
          </button>
          <button
            type="button"
            onClick={() => {
              setEditing(true);
              setDraftValue(draftValueToString(attribute.normalized_value ?? attribute.proposed_value));
            }}
            disabled={busy !== null}
            className="tap-target rounded-md border border-[var(--color-brand)] px-3 py-2 text-xs font-medium text-[var(--color-brand)] disabled:opacity-50"
          >
            수정
          </button>
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={busy !== null}
            className="tap-target rounded-md border border-[var(--color-danger)] px-3 py-2 text-xs font-medium text-[var(--color-danger)] disabled:opacity-50"
          >
            삭제(채택 안함)
          </button>
        </div>
      )}

      {!decided && editing && (
        <div className="mt-3 flex flex-col gap-2 rounded-md bg-[var(--color-surface-muted)] p-3">
          {isCapability ? (
            <select value={draftValue} onChange={(event) => setDraftValue(event.target.value)} className="input">
              <option value="UNKNOWN">{CAPABILITY_VALUE_LABEL_KO.UNKNOWN}</option>
              {CAPABILITY_VALUES.map((status) => (
                <option key={status} value={status}>
                  {CAPABILITY_VALUE_LABEL_KO[status] ?? status}
                </option>
              ))}
            </select>
          ) : isNumeric ? (
            <input
              type="number"
              value={draftValue}
              onChange={(event) => setDraftValue(event.target.value)}
              className="input"
            />
          ) : isTaxonomyRef ? (
            <p className="text-xs text-[var(--color-text-muted)]">
              온톨로지 참조값 직접 수정은 아직 지원하지 않습니다(TODO: 개념 선택기 연동). 값을
              바꾸려면 삭제 후 운영자에게 재입력을 요청해 주세요.
            </p>
          ) : (
            <textarea
              value={draftValue}
              onChange={(event) => setDraftValue(event.target.value)}
              className="input"
              rows={2}
            />
          )}

          {wouldModifyBeUnknownToYes && (
            <div className="rounded-md border border-dashed border-[var(--color-warning)] bg-[var(--color-warning-bg)] p-2 text-xs">
              <p className="font-semibold text-[var(--color-warning)]">
                &lsquo;미확인&rsquo; -&gt; &lsquo;가능&rsquo; 전이입니다. 사유가 필요합니다.
              </p>
              <textarea
                value={justification}
                onChange={(event) => setJustification(event.target.value)}
                className="input mt-2"
                rows={2}
              />
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void runModify()}
              disabled={
                busy !== null || isTaxonomyRef || (wouldModifyBeUnknownToYes && !justification.trim())
              }
              className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-xs font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
            >
              {busy === "modify" ? "저장 중…" : "수정값 저장"}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={busy !== null}
              className="tap-target rounded-md border border-[var(--color-border)] px-3 py-2 text-xs"
            >
              취소
            </button>
          </div>
        </div>
      )}

      {!decided && showDeleteConfirm && (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-[var(--color-danger)] bg-[var(--color-danger-bg)] p-3">
          <p className="text-xs text-[var(--color-danger)]">
            이 AI 제안을 채택하지 않습니다(원본 문서·근거는 남습니다). 계속하시겠습니까?
          </p>
          <textarea
            value={deleteReason}
            onChange={(event) => setDeleteReason(event.target.value)}
            className="input"
            rows={2}
            placeholder="사유(선택)"
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void runDelete()}
              disabled={busy !== null}
              className="tap-target rounded-md bg-[var(--color-danger)] px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
            >
              {busy === "delete" ? "삭제 처리 중…" : "삭제 확정"}
            </button>
            <button
              type="button"
              onClick={() => setShowDeleteConfirm(false)}
              disabled={busy !== null}
              className="tap-target rounded-md border border-[var(--color-border)] px-3 py-2 text-xs"
            >
              취소
            </button>
          </div>
        </div>
      )}

      {decided && (
        <p className="mt-2 text-xs text-[var(--color-text-muted)]">
          현재 확정값: {formatDisplayValue(attribute.normalized_value ?? attribute.proposed_value)}
          {attribute.rejection_reason ? ` · 사유: ${attribute.rejection_reason}` : ""}
        </p>
      )}
    </div>
  );
}
