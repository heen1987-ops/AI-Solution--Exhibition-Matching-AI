import { MockDataBanner } from "@/components/MockDataBanner";
import { currentMockProfile } from "@/lib/mock-data";
import { ProfileEditForm } from "./ProfileEditForm";

/**
 * S-7. MY 정보. 프로파일 확인·수정, 수신동의 관리(W-6 연동)를 다룬다. 이번 Wave는
 * 로컬 state만 바꾸는 폼(제출 시 실제 저장 없음)으로 골격만 제공한다.
 */
export default function MyPage() {
  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">MY 정보</h1>
      </header>
      <ProfileEditForm profile={currentMockProfile} />
    </div>
  );
}
