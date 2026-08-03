import Link from "next/link";
import { CompanyCard } from "@/components/CompanyCard";
import { DataSourceBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { loadFavorites } from "@/lib/api-client";
import { parseMockScenario } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * S-4. 관심목록. GET /favorites를 우선 사용한다.
 */
export default async function FavoritesPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  const { state } = await searchParams;
  const favorites = await loadFavorites(parseMockScenario(state));

  return (
    <div className="flex flex-col gap-6">
      <DataSourceBanner source={favorites.source} notice={favorites.notice} />
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">관심목록</h1>
        <Link href="/favorites?state=empty" className="text-xs underline">
          빈 목록 보기
        </Link>
      </header>

      {favorites.data.length === 0 ? (
        <EmptyState
          title="저장한 업체가 없습니다"
          description="업체 상세(S-5)에서 '관심 저장'을 눌러 여기에 모아보세요."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {favorites.data.map((favorite) => (
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
