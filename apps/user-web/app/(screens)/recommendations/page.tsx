import Link from "next/link";
import { CompanyCard } from "@/components/CompanyCard";
import { MockDataBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { fetchRecommendations } from "@/lib/mock-api";
import { parseMockScenario } from "@/lib/types";

/**
 * S-2. 추천 업체·부스 목록. GENERAL_REGISTERED/BUYER_REGISTERED는 프로파일 기반
 * 개인화 추천(W-5)을 본다. GUEST_WEB 분기(키오스크 인계 결과 열람)는 이번 Wave
 * 스켈레톤에서는 다루지 않는다(주석으로만 남김 - 실제 분기는 WEB-GROUP-001).
 *
 * `?state=empty` / `?state=error` 쿼리로 빈 결과/오류 상태를 재현할 수 있다
 * (오류 시 이 폴더의 error.tsx가 처리한다).
 */
export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  const { state } = await searchParams;
  const scenario = parseMockScenario(state);
  const recommendations = await fetchRecommendations(scenario);

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">추천 업체·부스 목록</h1>
        <div className="flex gap-2 text-xs">
          <Link href="/recommendations" className="underline">
            기본
          </Link>
          <Link href="/recommendations?state=empty" className="underline">
            빈 결과 보기
          </Link>
          <Link href="/recommendations?state=error" className="underline">
            오류 상태 보기
          </Link>
        </div>
      </header>

      {recommendations.length === 0 ? (
        <EmptyState
          title="아직 추천할 업체가 없습니다"
          description="관심영역을 MY 정보(S-7)에서 설정하면 추천이 생성됩니다."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {recommendations.map((item) => (
            <CompanyCard
              key={item.company.id}
              company={item.company}
              meta={
                <ul className="flex flex-col gap-1 text-xs text-zinc-500 dark:text-zinc-400">
                  <li>추천 점수: {Math.round(item.score * 100)}점</li>
                  {item.reasons.map((reason) => (
                    <li key={reason}>· {reason}</li>
                  ))}
                </ul>
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
