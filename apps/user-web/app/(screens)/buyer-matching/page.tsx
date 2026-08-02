import { CompanyCard } from "@/components/CompanyCard";
import { MockDataBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { fetchBuyerMatches } from "@/lib/mock-api";
import type { MeetingStatus } from "@/lib/types";

const STATUS_LABEL: Record<MeetingStatus, string> = {
  NONE: "매칭 확인 전",
  REQUESTED: "상담 요청됨",
  CONFIRMED: "상담 수락됨",
  DECLINED: "상담 거절됨",
};

/**
 * S-6. 바이어 매칭. BUYER_REGISTERED 전용(W-3 §S-6) - 매칭 확인 → 비교 → 관심
 * 저장 → 상담 요청 흐름과 상담 현황을 한 화면에서 다룬다.
 *
 * 개인정보 규칙(AGENTS.md §8): 상담 수락(CONFIRMED) 전에는 연락처를 절대
 * 노출하지 않는다 - 아래 렌더링에서 `meetingStatus === "CONFIRMED"`일 때만
 * `contact`를 표시한다.
 */
export default async function BuyerMatchingPage() {
  const matches = await fetchBuyerMatches();

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">바이어 매칭</h1>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          이 화면은 BuyerNeed가 있는 BUYER_REGISTERED 사용자만 접근할 수 있습니다(실제 접근
          제어는 이후 Wave). 상담 요청 버튼은 시각적 흉내만 내며 실제 요청·수락·거절
          워크플로우는 구현하지 않습니다.
        </p>
      </header>

      {matches.length === 0 ? (
        <EmptyState title="아직 매칭된 업체가 없습니다" />
      ) : (
        <ul className="flex flex-col gap-3">
          {matches.map((match) => (
            <CompanyCard
              key={match.company.id}
              company={match.company}
              meta={
                <div className="flex flex-col gap-1 text-xs text-zinc-500 dark:text-zinc-400">
                  <p>
                    매칭 점수: {Math.round(match.matchScore * 100)}점 · 상태:{" "}
                    {STATUS_LABEL[match.meetingStatus]}
                  </p>
                  {match.meetingStatus === "CONFIRMED" && match.contact ? (
                    <p className="text-emerald-700 dark:text-emerald-300">
                      연락처: {match.contact.email} / {match.contact.phone}
                    </p>
                  ) : (
                    <p>연락처는 상담 수락 후 공개됩니다.</p>
                  )}
                </div>
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
