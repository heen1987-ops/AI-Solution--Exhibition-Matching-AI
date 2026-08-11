"use client";

/**
 * 알림 설정 (`/notifications/preferences`).
 *
 * 근거: 작업 지시(WAVE 2E USER-WEB-NOTIFICATION) GOAL - "Preferences screen distinguishing
 * mandatory operational notices (cannot be disabled) from optional notification types
 * (recommendation-ready, event-day reminders, post-event info) each with an in-app/email
 * toggle where email is only offered if the user has an email on file."
 *
 * 필수 알림은 "끌 수 없다"는 요구를 그대로 반영해 토글 컨트롤 자체를 보여주지 않고(끌 수
 * 있는 것처럼 보이는 비활성 스위치도 혼란을 줄 수 있어 피한다) "항상 알려드려요" 배지로만
 * 표시한다. 선택 알림만 실제 토글(`PreferenceToggle`)을 갖는다. 이메일 토글은 그 카테고리가
 * 이메일 채널을 지원할 때만(`email_enabled !== null`) 렌더링하고, 사용자에게 등록된
 * 이메일이 없으면(`email_on_file === false`) 비활성 상태 + 안내 문구로 보여준다.
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts` 편집 범위 밖 - 이 화면은
 * `features/notification-preferences/api.ts`·`types.ts`(로컬 정본, "가정 계약" - 근거는
 * 그 파일들의 docstring 참고)를 쓴다.
 */

import { useCallback, useEffect, useState } from "react";

import { ApiClientError } from "@/lib/api-client";

import { getNotificationPreferences, updateNotificationPreferences } from "@/features/notification-preferences/api";
import PreferenceToggle from "@/features/notification-preferences/components/PreferenceToggle";
import type {
  NotificationCategoryPreference,
  NotificationPreferencesResponse,
} from "@/features/notification-preferences/types";

type Channel = "in_app" | "email";

function pendingKey(categoryCode: string, channel: Channel): string {
  return `${categoryCode}:${channel}`;
}

export default function NotificationPreferencesPage() {
  const [prefs, setPrefs] = useState<NotificationPreferencesResponse | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const result = await getNotificationPreferences();
      setPrefs(result);
      setLoadState("loaded");
    } catch (err) {
      setLoadState("error");
      setLoadError(err instanceof ApiClientError ? err.message : "알림 설정을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleToggle = useCallback(
    async (category: NotificationCategoryPreference, channel: Channel) => {
      if (!prefs || category.mandatory) return;
      const key = pendingKey(category.category_code, channel);
      if (pendingKeys.has(key)) return;

      const currentValue = channel === "in_app" ? category.in_app_enabled : category.email_enabled;
      if (channel === "email" && (currentValue === null || !prefs.email_on_file)) return;
      const nextValue = !currentValue;
      const field = channel === "in_app" ? "in_app_enabled" : "email_enabled";

      const previous = prefs;
      setSaveError(null);
      setPendingKeys((prev) => new Set(prev).add(key));
      setPrefs({
        ...prefs,
        categories: prefs.categories.map((item) =>
          item.category_code === category.category_code ? { ...item, [field]: nextValue } : item,
        ),
      });

      try {
        const result = await updateNotificationPreferences({
          categories: [{ category_code: category.category_code, [field]: nextValue }],
        });
        setPrefs(result);
      } catch (err) {
        setPrefs(previous);
        setSaveError(err instanceof ApiClientError ? err.message : "설정을 저장하지 못했습니다.");
      } finally {
        setPendingKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    },
    [prefs, pendingKeys],
  );

  if (loadState === "loading") {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-6">
        <p role="status" aria-live="polite" style={{ color: "var(--color-text-muted)" }}>
          불러오는 중...
        </p>
      </div>
    );
  }

  if (loadState === "error" || !prefs) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-3 px-4 py-6">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {loadError}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="tap-target self-start rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: "var(--color-border)" }}
        >
          다시 시도
        </button>
      </div>
    );
  }

  const mandatory = prefs.categories.filter((category) => category.mandatory);
  const optional = prefs.categories.filter((category) => !category.mandatory);

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-bold">알림 설정</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          운영에 필요한 필수 알림은 끌 수 없어요. 선택 알림은 종류별로 앱 내 알림과 이메일을
          따로 켜고 끌 수 있어요.
        </p>
      </header>

      {saveError ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {saveError}
        </p>
      ) : null}

      {prefs.categories.length === 0 ? (
        <p style={{ color: "var(--color-text-muted)" }}>표시할 알림 설정이 없어요.</p>
      ) : (
        <>
          {mandatory.length > 0 ? (
            <section aria-labelledby="mandatory-heading" className="flex flex-col gap-3">
              <h2 id="mandatory-heading" className="text-base font-semibold">
                필수 알림
              </h2>
              <ul className="flex flex-col gap-2">
                {mandatory.map((category) => (
                  <li
                    key={category.category_code}
                    data-testid="preference-category"
                    data-mandatory="true"
                    className="flex items-center justify-between gap-3 rounded-lg border p-3"
                    style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                  >
                    <div className="flex flex-col">
                      <span className="text-sm font-medium">{category.label}</span>
                      <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                        {category.description}
                      </span>
                    </div>
                    <span
                      className="inline-flex w-fit shrink-0 items-center rounded-full border px-3 py-1 text-xs font-semibold"
                      style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
                    >
                      항상 알려드려요
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {optional.length > 0 ? (
            <section aria-labelledby="optional-heading" className="flex flex-col gap-3">
              <h2 id="optional-heading" className="text-base font-semibold">
                선택 알림
              </h2>
              <ul className="flex flex-col gap-3">
                {optional.map((category) => (
                  <li
                    key={category.category_code}
                    data-testid="preference-category"
                    data-mandatory="false"
                    className="flex flex-col gap-3 rounded-lg border p-3"
                    style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
                  >
                    <div className="flex flex-col">
                      <span className="text-sm font-medium">{category.label}</span>
                      <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
                        {category.description}
                      </span>
                    </div>
                    <PreferenceToggle
                      label={`${category.label} - 앱 내 알림`}
                      checked={category.in_app_enabled}
                      disabled={pendingKeys.has(pendingKey(category.category_code, "in_app"))}
                      onChange={() => void handleToggle(category, "in_app")}
                    />
                    {category.email_enabled !== null ? (
                      <PreferenceToggle
                        label={`${category.label} - 이메일 알림`}
                        checked={category.email_enabled}
                        disabled={!prefs.email_on_file || pendingKeys.has(pendingKey(category.category_code, "email"))}
                        onChange={() => void handleToggle(category, "email")}
                        hint={!prefs.email_on_file ? "이메일을 등록하면 사용할 수 있어요" : undefined}
                      />
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
