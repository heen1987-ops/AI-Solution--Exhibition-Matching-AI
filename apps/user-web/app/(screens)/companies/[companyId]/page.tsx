import { notFound } from "next/navigation";
import { DataSourceBanner } from "@/components/MockDataBanner";
import { SaveFavoriteButton } from "./SaveFavoriteButton";
import { loadCompanyById, loadProfile } from "@/lib/api-client";

export const dynamic = "force-dynamic";

/**
 * S-5. 업체·부스 상세. 공개 getExhibitor/getBooth API를 우선 사용한다.
 */
export default async function CompanyDetailPage({
  params,
}: {
  params: Promise<{ companyId: string }>;
}) {
  const { companyId } = await params;
  const [companyState, profileState] = await Promise.all([
    loadCompanyById(companyId),
    loadProfile(),
  ]);
  const company = companyState.data;

  if (!company) {
    notFound();
  }

  const canSaveFavorite = profileState.data.userType !== "GUEST_WEB";

  return (
    <div className="flex flex-col gap-6">
      <DataSourceBanner source={companyState.source} notice={companyState.notice} />
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

      {canSaveFavorite ? (
        <SaveFavoriteButton companyName={company.name} recommendableId={company.recommendableId} />
      ) : null}
    </div>
  );
}
