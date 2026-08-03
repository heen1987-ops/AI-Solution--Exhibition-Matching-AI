"use client";

import { useState } from "react";

type FavoriteButtonStatus = "idle" | "saving" | "saved" | "error";

type FavoriteResponse = {
  saved_recommendable_id?: string;
};

/**
 * "관심 저장" 버튼. 브라우저에 공개된 API/Profile 환경이 있으면 POST /favorites와
 * DELETE /favorites/{id}를 호출하고, 로컬 데모 환경에서는 버튼 상태만 토글한다.
 */
export function SaveFavoriteButton({
  companyName,
  recommendableId,
}: {
  companyName: string;
  recommendableId?: string;
}) {
  const [status, setStatus] = useState<FavoriteButtonStatus>("idle");
  const [savedFavoriteId, setSavedFavoriteId] = useState<string | null>(null);
  const saved = status === "saved";
  const disabled = !recommendableId || status === "saving";

  async function handleClick() {
    if (!recommendableId || status === "saving") {
      return;
    }

    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(/\/+$/, "");
    if (!baseUrl) {
      setStatus(saved ? "idle" : "saved");
      return;
    }

    setStatus("saving");
    try {
      if (saved) {
        if (savedFavoriteId) {
          await fetch(`${baseUrl}/api/v1/favorites/${savedFavoriteId}`, {
            method: "DELETE",
            headers: favoriteHeaders(),
          });
        }
        setSavedFavoriteId(null);
        setStatus("idle");
        return;
      }

      const response = await fetch(`${baseUrl}/api/v1/favorites`, {
        method: "POST",
        headers: favoriteHeaders(),
        body: JSON.stringify({
          recommendable_id: recommendableId,
          saved_context_json: { source: "user-web-company-detail" },
        }),
      });

      if (!response.ok && response.status !== 409) {
        throw new Error(`HTTP_${response.status}`);
      }

      const body = response.status === 409 ? {} : ((await response.json()) as FavoriteResponse);
      setSavedFavoriteId(body.saved_recommendable_id ?? null);
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-pressed={saved}
      disabled={disabled}
      className={`w-fit rounded-full px-4 py-2 text-sm font-medium ${
        saved
          ? "bg-emerald-600 text-white"
          : recommendableId
            ? "border border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-200"
            : "cursor-not-allowed border border-zinc-200 text-zinc-400 dark:border-zinc-800"
      }`}
    >
      {buttonLabel(status, companyName)}
    </button>
  );
}

function favoriteHeaders(): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const profileId = process.env.NEXT_PUBLIC_MEETAI_PROFILE_ID?.trim();
  const userId = process.env.NEXT_PUBLIC_MEETAI_USER_ID?.trim();
  const userType = process.env.NEXT_PUBLIC_MEETAI_USER_TYPE?.trim();
  const actorRole = process.env.NEXT_PUBLIC_MEETAI_ACTOR_ROLE?.trim();
  if (profileId) {
    headers["X-MeetAI-Profile-Id"] = profileId;
  }
  if (userId) {
    headers["X-MeetAI-User-Id"] = userId;
  }
  if (userType) {
    headers["X-MeetAI-User-Type"] = userType;
  }
  if (actorRole) {
    headers["X-MeetAI-Actor-Role"] = actorRole;
  }
  return headers;
}

function buttonLabel(status: FavoriteButtonStatus, companyName: string): string {
  if (status === "saving") {
    return "저장 중";
  }
  if (status === "saved") {
    return `${companyName} 관심 저장됨`;
  }
  if (status === "error") {
    return "저장 실패, 다시 시도";
  }
  return "관심 저장";
}
