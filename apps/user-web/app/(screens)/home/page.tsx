import Link from "next/link";
import { CompanyCard } from "@/components/CompanyCard";
import { MockDataBanner } from "@/components/MockDataBanner";
import { currentMockProfile } from "@/lib/mock-data";
import { fetchRecommendations } from "@/lib/mock-api";

/**
 * S-1. 개인화 홈 (docs/redesign-v2/web/W-3-screen-ia.md).
 * GENERAL_REGISTERED/BUYER_REGISTERED 전용 - 오늘의 추천 상위 N개 + 관심목록/바이어
 * 매칭 바로가기. 이번 Wave는 Mock 데이터만 사용, 사용자 유형 분기는 하드코딩된
 * `currentMockProfile`로 흉내낸다(실 인증은 이후 Wave).
 */
export default async function HomePage() {
  const recommendations = await fetchRecommendations();
  const topRecommendations = recommendations.slice(0, 2);

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          안녕하세요, {currentMockProfile.displayName}님
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
        {currentMockProfile.userType === "BUYER_REGISTERED" ? (
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
