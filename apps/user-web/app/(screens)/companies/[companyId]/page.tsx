import { notFound } from "next/navigation";
import { MockDataBanner } from "@/components/MockDataBanner";
import { SaveFavoriteButton } from "./SaveFavoriteButton";
import { fetchCompanyById } from "@/lib/mock-api";
import { currentMockProfile } from "@/lib/mock-data";

/**
 * S-5. 업체·부스 상세. 3개 사용자 유형 모두 접근 가능한 유일한 화면(W-3 §S-5) -
 * 업체 공개 정보는 로그인 여부와 무관하다. GUEST_WEB에게는 "관심 저장" 버튼이
 * 노출되지 않는다(S-4와 동일 원칙) - 이번 Wave는 `currentMockProfile`로 흉내낸다.
 */
export default async function CompanyDetailPage({
  params,
}: {
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  const company = await fetchCompanyById(companyId);

  if (!company) {
    notFound();
  }

  const canSaveFavorite = currentMockProfile.userType !== "GUEST_WEB";

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {company.categoryLabel} · {company.zone} {company.boothNumber}
        </p>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">{company.name}</h1>
      </header>

      <p className="text-sm text-zinc-600 dark:text-zinc-300">{company.summary}</p>

      <ul className="flex flex-wrap gap-1">
        {company.tags.map((tag) => (
          <li
            key={tag}
            className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            #{tag}
          </li>
        ))}
      </ul>

      {canSaveFavorite ? <SaveFavoriteButton companyName={company.name} /> : null}
    </div>
  );
}
