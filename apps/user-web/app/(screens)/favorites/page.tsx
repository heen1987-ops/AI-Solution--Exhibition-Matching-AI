import Link from "next/link";
import { CompanyCard } from "@/components/CompanyCard";
import { MockDataBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { fetchFavorites } from "@/lib/mock-api";
import { parseMockScenario } from "@/lib/types";

/**
 * S-4. 관심목록. `profile.saved_recommendable`(CTR-006, 아직 미생성) 스키마의
 * 화면단 소비처 - 이번 Wave는 Mock 데이터만 사용한다. GUEST_WEB은 지속 프로파일이
 * 없어 이 화면 자체가 노출되지 않는다(W-3 §S-4) - 실제 접근 제어는 이후 Wave.
 */
export default async function FavoritesPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  const { state } = await searchParams;
  const favorites = await fetchFavorites(parseMockScenario(state));

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">관심목록</h1>
        <Link href="/favorites?state=empty" className="text-xs underline">
          빈 목록 보기
        </Link>
      </header>

      {favorites.length === 0 ? (
        <EmptyState
          title="저장한 업체가 없습니다"
          description="업체 상세(S-5)에서 '관심 저장'을 눌러 여기에 모아보세요."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {favorites.map((favorite) => (
            <CompanyCard
              key={favorite.id}
              company={favorite.company}
              meta={
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  저장일: {new Date(favorite.savedAt).toLocaleDateString("ko-KR")}
                  {favorite.savedZone ? ` · 저장 시점 존: ${favorite.savedZone}` : ""}
                </p>
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
