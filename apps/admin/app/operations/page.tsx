"use client";

/**
 * 운영 허브 (ADMIN-OPERATIONS, WAVE 2E).
 *
 * 이 트랙이 만든 두 운영 화면(무응답 검색 운영, 업체별 데이터 품질)의 진입점.
 * `apps/admin/components/SideNav.tsx`는 공유 컴포넌트(다른 트랙 소유 경로)라 이 작업에서는
 * 수정하지 않는다 - 내비게이션 통합은 별도 통합 단계에서 처리된다. 이 페이지 자체가
 * `/operations`의 목적지 역할을 한다.
 */

import Link from "next/link";

export default function OperationsHubPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">운영</h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          검색 품질을 사람이 검토·개선 요청하는 화면 모음입니다. AI는 어떤 화면에서도 온톨로지·
          업체 데이터를 자동으로 수정하지 않습니다 - 모든 개선은 담당자에게 가는 요청/플래그입니다.
        </p>
      </div>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <OperationsLinkCard
          href="/analytics/no-results"
          title="무응답(0건) 검색 운영"
          description="정규화 질의·발생 건수·채널·PII 마스킹 상태를 확인하고, 원인을 분류해 동의어 추가·온톨로지 검토·업체 데이터 보완 등 개선 액션을 요청합니다."
        />
        <OperationsLinkCard
          href="/operations/data-quality"
          title="업체별 데이터 품질"
          description="필수필드 충족률·제품/관심코드 등록·문서 검토·검색 색인 상태와, 오직 데이터 존재 여부로만 계산한 완성도 점수를 확인합니다."
        />
      </section>
    </div>
  );
}

function OperationsLinkCard({
  href,
  title,
  description,
}: {
  href: string;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="tap-target flex flex-col gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 hover:border-[var(--color-brand)]"
    >
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="text-xs text-[var(--color-text-muted)]">{description}</p>
    </Link>
  );
}
