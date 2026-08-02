"use client";

import { useState } from "react";
import type { UserProfile } from "@/lib/types";

/**
 * 로컬 state만 갱신하는 폼 - 제출해도 아무 곳에도 저장되지 않는다(실제 저장은
 * `PATCH /profile` 계약 확정 및 WEB-GROUP-001 구현 이후).
 */
export function ProfileEditForm({ profile }: { profile: UserProfile }) {
  const [displayName, setDisplayName] = useState(profile.displayName);
  const [marketingOptIn, setMarketingOptIn] = useState(profile.marketingOptIn);
  const [savedNotice, setSavedNotice] = useState(false);

  return (
    <form
      className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      onSubmit={(event) => {
        event.preventDefault();
        setSavedNotice(true);
      }}
    >
      <div>
        <span className="text-xs text-zinc-500 dark:text-zinc-400">사용자 유형</span>
        <p className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{profile.userType}</p>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-zinc-600 dark:text-zinc-300">표시 이름</span>
        <input
          type="text"
          value={displayName}
          onChange={(event) => {
            setDisplayName(event.target.value);
            setSavedNotice(false);
          }}
          className="rounded-md border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>

      <div className="flex flex-col gap-1 text-sm">
        <span className="text-zinc-600 dark:text-zinc-300">관심영역</span>
        <ul className="flex flex-wrap gap-1">
          {profile.interestAreas.map((area) => (
            <li
              key={area}
              className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
            >
              #{area}
            </li>
          ))}
        </ul>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={marketingOptIn}
          onChange={(event) => {
            setMarketingOptIn(event.target.checked);
            setSavedNotice(false);
          }}
        />
        <span className="text-zinc-600 dark:text-zinc-300">마케팅 정보 수신 동의</span>
      </label>

      <button
        type="submit"
        className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
      >
        저장 (Mock)
      </button>
      {savedNotice ? (
        <p className="text-xs text-emerald-700 dark:text-emerald-300">
          화면에만 반영되었습니다. 실제 저장은 이번 Wave에서 구현하지 않습니다.
        </p>
      ) : null}
    </form>
  );
}
