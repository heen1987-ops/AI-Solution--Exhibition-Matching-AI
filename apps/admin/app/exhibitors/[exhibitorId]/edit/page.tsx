"use client";

/**
 * 업체 수정 폼 (작업 지시 필수 요구사항).
 *
 * 실제로 동작하는 08 28.1/28.2절 엔드포인트를 그대로 쓴다:
 *   GET   /exhibitors/{id}/profile              (공개, 조회)
 *   PATCH /partner/exhibitors/{id}/profile       (EXHIBITOR/OPERATOR/ADMIN 역할 필요)
 * 후자는 세션의 actorUserId가 실제로 그 업체 소속 EXHIBITOR이거나 OPERATOR/ADMIN 역할을
 * 가진 DB 레코드여야 성공한다(apps/api/app/api/v1/routers/partner.py
 * `_require_exhibitor_access`) - 잘못된 세션이면 진짜 403이 뜬다.
 */

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { getExhibitorProfile, updateExhibitorProfile } from "@/lib/api-client";
import type { ExhibitorProfileRead } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

export default function EditExhibitorPage() {
  const params = useParams<{ exhibitorId: string }>();
  const router = useRouter();
  const exhibitorId = params.exhibitorId;

  const [profile, setProfile] = useState<ExhibitorProfileRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const [companySummary, setCompanySummary] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getExhibitorProfile(exhibitorId)
      .then((data) => {
        setProfile(data);
        setCompanySummary(data.company_summary ?? "");
        setWebsiteUrl(data.website_url ?? "");
      })
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [exhibitorId]);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async () => {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const updated = await updateExhibitorProfile(exhibitorId, {
        company_summary: companySummary || null,
        website_url: websiteUrl || null,
      });
      setProfile(updated);
      setSaved(true);
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">업체 수정</h1>
        <button
          type="button"
          onClick={() => router.push(`/exhibitors/${exhibitorId}/review`)}
          className="tap-target text-sm text-[var(--color-brand)] underline"
        >
          검수 화면으로
        </button>
      </div>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={load} /> : null}

      {!loading && !error && profile && (
        <>
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm">
            <p className="font-semibold">{profile.company_name}</p>
            <p className="mt-1 text-[var(--color-text-muted)]">
              현재 승인상태: <StatusBadge status={profile.master_approval_status} /> · 완성도{" "}
              {profile.data_completeness_percent}% · 버전 v{profile.current_profile_version}
            </p>
            <p className="mt-2 text-xs text-[var(--color-text-muted)]">
              법인명은 원천 신뢰가 필요해 이 화면에서 바꿀 수 없습니다(업체 등록 화면의 배치
              import를 통해서만 변경). 08 문서 31.1절 ‘업체·운영자 충돌’ 원칙에 따라, 이 폼을
              저장하면 승인상태가 DRAFT로 되돌아가 재검수가 필요합니다.
            </p>
          </div>

          <RoleGate
            capability="EXHIBITOR_EDIT_OWN"
            fallback={
              <p className="text-sm text-[var(--color-text-muted)]">
                현재 역할에는 업체 정보 수정 권한이 없습니다.
              </p>
            }
          >
            {saveError ? <ErrorBanner error={saveError} /> : null}
            {saved && (
              <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
                저장되었습니다.
              </p>
            )}
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void submit();
              }}
              className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
            >
              <Field label="업체소개">
                <textarea
                  value={companySummary}
                  onChange={(event) => setCompanySummary(event.target.value)}
                  className="input"
                  rows={4}
                />
              </Field>
              <Field label="웹사이트">
                <input
                  value={websiteUrl}
                  onChange={(event) => setWebsiteUrl(event.target.value)}
                  className="input"
                  placeholder="https://"
                />
              </Field>
              <button
                type="submit"
                disabled={saving}
                className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
              >
                {saving ? "저장 중…" : "저장"}
              </button>
            </form>
          </RoleGate>
        </>
      )}
    </div>
  );
}
