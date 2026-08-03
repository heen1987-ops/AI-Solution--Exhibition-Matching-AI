import Link from "next/link";
import { CompanyCard } from "@/components/CompanyCard";
import { DataSourceBanner } from "@/components/MockDataBanner";
import { loadProfile, loadRecommendations } from "@/lib/api-client";

export const dynamic = "force-dynamic";

/**
 * S-1. 개인화 홈. 실제 profile/recommendations API를 우선 사용하고, 로컬 API가 없으면
 * 동일 화면 타입의 fallback 데이터로 렌더링한다.
 */
export default async function HomePage() {
  const [profileState, recommendationState] = await Promise.all([
    loadProfile(),
    loadRecommendations(),
  ]);
  const profile = profileState.data;
  const topRecommendations = recommendationState.data.slice(0, 2);
  const source =
    profileState.source === "api" || recommendationState.source === "api" ? "api" : "fallback";

  return (
    <div className="flex flex-col gap-6">
      <DataSourceBanner
        source={source}
        notice={profileState.notice ?? recommendationState.notice}
      />
      <header>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          안녕하세요, {profile.displayName}님
        </p>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">
          오늘의 추천 업체·부스
        </h1>
      </header>

      <ul className="flex flex-col gap-3">
        {topRecommendations.map((item) => (
          <CompanyCard
            key={item.company.id}
            company={item.company}
            meta={<p className="text-xs text-zinc-500 dark:text-zinc-400">{item.reasons[0]}</p>}
          />
        ))}
      </ul>

      <div className="flex flex-wrap gap-3 text-sm">
        <Link
          href="/recommendations"
          className="rounded-full bg-zinc-900 px-4 py-2 font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          추천 목록 전체 보기
        </Link>
        <Link
          href="/favorites"
          className="rounded-full border border-zinc-300 px-4 py-2 font-medium text-zinc-700 dark:border-zinc-700 dark:text-zinc-200"
        >
          관심목록 바로가기
        </Link>
        {profile.userType === "BUYER_REGISTERED" ? (
          <Link
            href="/buyer-matching"
            className="rounded-full border border-zinc-300 px-4 py-2 font-medium text-zinc-700 dark:border-zinc-700 dark:text-zinc-200"
          >
            바이어 매칭 바로가기
          </Link>
        ) : null}
      </div>
    </div>
  );
}
