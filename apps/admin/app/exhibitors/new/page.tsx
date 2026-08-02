"use client";

/**
 * 업체 등록 폼 (작업 지시 필수 요구사항).
 *
 * 실제로 동작하는 `POST /admin/imports/exhibitors`(apps/api/app/api/v1/routers/imports.py,
 * 이미 구현·검증됨)를 1행짜리 배치로 호출한다. 이 엔드포인트는 `source_record_id` 기준
 * upsert라서 같은 값으로 다시 제출하면 "등록"이 아니라 "수정"이 된다(멱등) - 업체 등록/수정을
 * 하나의 폼으로 자연스럽게 커버한다.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiPost } from "@/lib/api-client";
import type { ImportBatchResult } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

export default function NewExhibitorPage() {
  const router = useRouter();
  const [tenantId, setTenantId] = useState("");
  const [eventId, setEventId] = useState("");
  const [sourceRecordId, setSourceRecordId] = useState("");
  const [legalName, setLegalName] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [story, setStory] = useState("");
  const [managerName, setManagerName] = useState("");
  const [managerPhone, setManagerPhone] = useState("");
  const [managerEmail, setManagerEmail] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<ImportBatchResult | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiPost<ImportBatchResult>("/admin/imports/exhibitors", {
        tenant_id: tenantId,
        event_id: eventId,
        rows: [
          {
            source_record_id: sourceRecordId,
            source_updated_at: new Date().toISOString(),
            legal_name: legalName,
            display_name: displayName || null,
            website_url: websiteUrl || null,
            story: story || null,
            manager_name: managerName || null,
            manager_phone: managerPhone || null,
            manager_email: managerEmail || null,
          },
        ],
      });
      setResult(res);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">업체 등록</h1>
      <p className="text-sm text-[var(--color-text-muted)]">
        <code>POST /admin/imports/exhibitors</code>를 호출합니다(실제 동작, 인증 미들웨어는
        아직 없어 OPERATOR 권한 검사가 서버에 없습니다 - imports.py 모듈 TODO 참고). 같은{" "}
        <b>원천 레코드 ID</b>로 다시 제출하면 새로 만들지 않고 기존 업체를 갱신합니다.
      </p>

      {error ? <ErrorBanner error={error} /> : null}

      {result && (
        <div
          role="status"
          className={`rounded-lg border p-4 text-sm ${
            result.failed_rows > 0
              ? "border-[var(--color-warning)] bg-[var(--color-warning-bg)]"
              : "border-[var(--color-success)] bg-[var(--color-success-bg)]"
          }`}
        >
          <p className="font-semibold">처리 결과: {result.status}</p>
          <p>
            성공 {result.success_rows}건 / 실패 {result.failed_rows}건 (총 {result.total_rows}건)
          </p>
          {result.errors.map((rowError) => (
            <p key={rowError.row_index} className="mt-1 text-xs">
              행 {rowError.row_index}: [{rowError.error_code}] {rowError.message}
            </p>
          ))}
          {result.failed_rows === 0 && (
            <button
              type="button"
              onClick={() => router.push("/exhibitors")}
              className="tap-target mt-3 rounded-md border border-current px-3 py-1.5 text-xs font-medium"
            >
              업체 목록으로
            </button>
          )}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="테넌트 ID" required hint="UUID">
            <input required value={tenantId} onChange={(e) => setTenantId(e.target.value)} className="input font-mono text-xs" />
          </Field>
          <Field label="행사 ID" required hint="UUID">
            <input required value={eventId} onChange={(e) => setEventId(e.target.value)} className="input font-mono text-xs" />
          </Field>
        </div>

        <Field label="원천 레코드 ID" required hint="같은 값으로 재제출하면 수정(upsert)됩니다">
          <input required value={sourceRecordId} onChange={(e) => setSourceRecordId(e.target.value)} className="input" />
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="법인명" required>
            <input required value={legalName} onChange={(e) => setLegalName(e.target.value)} className="input" />
          </Field>
          <Field label="전시명(간판명)">
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="input" />
          </Field>
        </div>

        <Field label="웹사이트">
          <input value={websiteUrl} onChange={(e) => setWebsiteUrl(e.target.value)} className="input" placeholder="https://" />
        </Field>

        <Field label="업체소개">
          <textarea value={story} onChange={(e) => setStory(e.target.value)} className="input" rows={3} />
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <Field label="담당자명">
            <input value={managerName} onChange={(e) => setManagerName(e.target.value)} className="input" />
          </Field>
          <Field label="담당자 연락처">
            <input value={managerPhone} onChange={(e) => setManagerPhone(e.target.value)} className="input" />
          </Field>
          <Field label="담당자 이메일">
            <input value={managerEmail} onChange={(e) => setManagerEmail(e.target.value)} className="input" />
          </Field>
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {submitting ? "등록 중…" : "등록"}
        </button>
      </form>
    </div>
  );
}
