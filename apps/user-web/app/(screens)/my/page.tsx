import { DataSourceBanner } from "@/components/MockDataBanner";
import { loadProfile } from "@/lib/api-client";
import { ProfileEditForm } from "./ProfileEditForm";

export const dynamic = "force-dynamic";

/**
 * S-7. MY 정보. GET /profile/me를 우선 사용한다.
 */
export default async function MyPage() {
  const profile = await loadProfile();
  return (
    <div className="flex flex-col gap-6">
      <DataSourceBanner source={profile.source} notice={profile.notice} />
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">MY 정보</h1>
      </header>
      <ProfileEditForm profile={profile.data} />
    </div>
  );
}
