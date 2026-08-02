"use client";

import { useState } from "react";

/**
 * 시각적 흉내만 내는 "관심 저장" 버튼 - 로컬 state만 토글하며 서버에 아무것도
 * 쓰지 않는다(실 저장 API는 WEB-GROUP-001에서 `profile.saved_recommendable`
 * 확정 이후 구현).
 */
export function SaveFavoriteButton({ companyName }: { companyName: string }) {
  const [saved, setSaved] = useState(false);

  return (
    <button
      type="button"
      onClick={() => setSaved((prev) => !prev)}
      aria-pressed={saved}
      className={`w-fit rounded-full px-4 py-2 text-sm font-medium ${
        saved
          ? "bg-emerald-600 text-white"
          : "border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200"
      }`}
    >
      {saved ? `${companyName} 관심 저장됨` : "관심 저장"}
    </button>
  );
}
