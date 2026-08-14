"use client";

/**
 * U-20 추천 조건 수정.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md
 *     5.1절 라우트 표: `/profile/preferences`, 핵심 API `PATCH /profiles/{id}`(실제 경로는
 *     인터페이스 명세 14절 `PATCH /profiles/me` - `frontend/lib/api-client.ts`의
 *     `updateProfilePreferences`).
 *     U-20절: "목적, 주종, 가격, 남은 시간, 이동 선호를 한 화면에서 수정한다. 변경 후 새
 *     추천버전을 생성하고 이전 추천은 감사·분석 목적으로 보존한다."
 * - frontend/lib/types.ts
 *     "14절 프로파일 일반 갱신 (U-20)" 섹션의 `ProfileGeneralPatchRequest`(주종·가격은
 *     add/remove 델타 또는 값 전체 교체) - 이 화면의 1차 데이터 계약.
 *     "8.1절 방문 목적 (U-04)"의 `GoalsUpdateRequest`(목적은 전체 교체) - `postAnswers`의
 *     GOALS 스텝.
 *     "8.4절 방문 계획 (U-07)"의 `VisitPlanRequest`(남은 시간·이동 선호) - `postAnswers`의
 *     VISIT_PLAN 스텝.
 *
 * 코드값 출처에 대한 메모 (중요)
 * -------------------------------
 * 작업 지시: "6단계 매칭 온톨로지 문서가 아직 없다. 태그·속성 코드값은 하드코딩 enum을
 * 피한다." 그래서 "목적"과 "주종" 선택지는 `frontend/lib/ontology.ts`를 통해 실제 서비스
 * 중인 온톨로지 카탈로그(`GET /api/v1/ontology/concepts`)에서 동적으로 가져온다:
 *   - 목적: 일반 관람객은 `VISIT_GOAL`, 바이어는 `BUSINESS_GOAL` concept_type.
 *   - 주종: `PRODUCT_CATEGORY` concept_type 중 코드가 `ALCOHOL.`로 시작하는 항목만 걸러
 *     보여준다(주류 하위 분류만 노출 - `PRODUCT.*` 최상위 카테고리는 제외).
 * 온톨로지 조회가 실패해도 화면을 막지 않는다 - 목적은 자유 서술(`free_text_goal`)로,
 * 주종은 해당 섹션만 비활성 안내로 대체한다.
 * 반대로 "이동 선호"의 `route_preference` 세 값(`LOW_CONGESTION`/`SHORTEST`/
 * `RECOMMENDED_FIRST`)은 열린 온톨로지 코드가 아니라 `frontend/lib/types.ts`가 이미 타입
 * 후보로 못박아 둔 값이라 그대로 상수로 쓴다(하드코딩 금지 원칙은 "아직 설계되지 않은
 * taxonomy 코드"에 적용되는 것이지, 이미 계약된 타입 리터럴에는 적용되지 않는다).
 */

import { useEffect, useState, type ReactNode } from "react";

import { ApiClientError, getProfile, postAnswers, updateProfilePreferences } from "@/lib/api-client";
import { fetchOntologyConcepts, type OntologyConcept } from "@/lib/ontology";
import type { GoalItem, ProfileGeneralPatchRequest, ProfileView } from "@/lib/types";

const ROUTE_PREFERENCE_OPTIONS: Array<{ code: "SHORTEST" | "RECOMMENDED_FIRST" | "LOW_CONGESTION"; label: string }> = [
  { code: "SHORTEST", label: "가까운 곳" },
  { code: "RECOMMENDED_FIRST", label: "추천 우선" },
  { code: "LOW_CONGESTION", label: "혼잡 적은 곳" },
];

const AVAILABLE_MINUTES_PRESETS: Array<{ value: string; label: string }> = [
  { value: "30", label: "30분" },
  { value: "60", label: "1시간" },
  { value: "120", label: "2시간" },
  { value: "", label: "여유 있음" },
];

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function toggleCode(list: string[], code: string): string[] {
  return list.includes(code) ? list.filter((item) => item !== code) : [...list, code];
}

function Chip({
  label,
  selected,
  onClick,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={selected}
      onClick={onClick}
      className="tap-target rounded-full border px-3 text-sm font-medium"
      style={{
        borderColor: selected ? "var(--color-brand)" : "var(--color-border)",
        backgroundColor: selected ? "var(--color-brand)" : "transparent",
        color: selected ? "var(--color-brand-contrast)" : "var(--color-text)",
      }}
    >
      {label}
    </button>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      className="flex flex-col gap-3 rounded-xl border p-4"
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      <h2 className="text-base font-bold">{title}</h2>
      {children}
    </section>
  );
}

export default function ProfilePreferencesPage() {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [profileLoadState, setProfileLoadState] = useState<"loading" | "loaded" | "error">("loading");
  const [profileError, setProfileError] = useState<string | null>(null);

  // 목적
  const [goalOptions, setGoalOptions] = useState<OntologyConcept[]>([]);
  const [goalOptionsError, setGoalOptionsError] = useState<string | null>(null);
  const [selectedGoals, setSelectedGoals] = useState<string[]>([]);
  const [freeTextGoal, setFreeTextGoal] = useState("");
  const [goalsDirty, setGoalsDirty] = useState(false);

  // 주종
  const [categoryOptions, setCategoryOptions] = useState<OntologyConcept[]>([]);
  const [categoryOptionsError, setCategoryOptionsError] = useState<string | null>(null);
  const [initialCategories, setInitialCategories] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [categoriesDirty, setCategoriesDirty] = useState(false);

  // 가격
  const [priceMin, setPriceMin] = useState("");
  const [priceMax, setPriceMax] = useState("");
  const [priceDirty, setPriceDirty] = useState(false);

  // 남은 시간 · 이동 선호
  const [visitDate, setVisitDate] = useState(todayIso());
  const [availableMinutes, setAvailableMinutes] = useState("");
  const [routePreference, setRoutePreference] = useState<string | null>(null);
  const [minimizeDistance, setMinimizeDistance] = useState(false);
  const [accessibleRoute, setAccessibleRoute] = useState(false);
  const [visitPlanDirty, setVisitPlanDirty] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveResultMessage, setSaveResultMessage] = useState<string | null>(null);
  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getProfile();
        if (cancelled) return;
        setProfile(data);
        setSelectedGoals(data.goals.map((goal) => goal.attribute_code));

        const prefs = (data.consumer_preferences ?? {}) as Record<string, unknown>;
        const categories = isStringArray(prefs.product_categories) ? prefs.product_categories : [];
        setInitialCategories(categories);
        setSelectedCategories(categories);

        const price = prefs.price as { min_amount?: number | null; max_amount?: number | null } | undefined;
        if (price && typeof price === "object") {
          setPriceMin(price.min_amount != null ? String(price.min_amount) : "");
          setPriceMax(price.max_amount != null ? String(price.max_amount) : "");
        }

        setProfileLoadState("loaded");
      } catch (err) {
        if (cancelled) return;
        setProfileLoadState("error");
        setProfileError(err instanceof ApiClientError ? err.message : "프로파일을 불러오지 못했습니다.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!profile) return;
    const conceptType = profile.user_type === "BUYER" ? "BUSINESS_GOAL" : "VISIT_GOAL";
    let cancelled = false;
    fetchOntologyConcepts({ conceptType })
      .then((items) => {
        if (!cancelled) setGoalOptions(items);
      })
      .catch(() => {
        if (!cancelled) setGoalOptionsError("목적 목록을 불러오지 못했어요. 아래 자유 서술로 알려주세요.");
      });
    return () => {
      cancelled = true;
    };
  }, [profile]);

  useEffect(() => {
    let cancelled = false;
    fetchOntologyConcepts({ conceptType: "PRODUCT_CATEGORY" })
      .then((items) => {
        if (cancelled) return;
        setCategoryOptions(items.filter((item) => item.code.startsWith("ALCOHOL.")));
      })
      .catch(() => {
        if (!cancelled) setCategoryOptionsError("주종 목록을 불러오지 못했어요.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSaveAll() {
    setSaving(true);
    setSaveErrorMessage(null);
    setSaveResultMessage(null);
    const savedSections: string[] = [];
    let refreshRequired = false;

    try {
      if (goalsDirty) {
        const visitGoals: GoalItem[] = selectedGoals.map((code, index) => ({ code, priority: index + 1 }));
        await postAnswers({
          step: "GOALS",
          data: { visit_goals: visitGoals, free_text_goal: freeTextGoal.trim() || null },
        });
        savedSections.push("목적");
      }

      const patch: ProfileGeneralPatchRequest = {};
      let hasPatch = false;

      if (categoriesDirty) {
        const add = selectedCategories.filter((code) => !initialCategories.includes(code));
        const remove = initialCategories.filter((code) => !selectedCategories.includes(code));
        if (add.length > 0 || remove.length > 0) {
          patch.product_categories = { add, remove };
          hasPatch = true;
        }
      }

      if (priceDirty) {
        patch.price = {
          min_amount: priceMin.trim() ? Number(priceMin) : null,
          max_amount: priceMax.trim() ? Number(priceMax) : null,
          currency: "KRW",
        };
        hasPatch = true;
      }

      if (hasPatch) {
        const response = await updateProfilePreferences(
          patch,
          profile ? { ifMatch: `profile-v${profile.current_version}` } : undefined,
        );
        refreshRequired = refreshRequired || response.recommendation_refresh_required;
        savedSections.push("주종·가격");
      }

      if (visitPlanDirty) {
        await postAnswers({
          step: "VISIT_PLAN",
          data: {
            visit_date: visitDate,
            available_minutes: availableMinutes ? Number(availableMinutes) : null,
            route_preference: routePreference,
            walking_constraints: { minimize_distance: minimizeDistance, accessible_route: accessibleRoute },
            // TODO(상담 가능 시간 슬롯 편집 UI): 이 화면은 U-07 온보딩과 달리 슬롯 편집을
            // 다루지 않는다 - 빈 배열은 "이번 저장에서 슬롯을 바꾸지 않음"으로 간주한다.
            meeting_available_slots: [],
          },
        });
        savedSections.push("체류시간·이동선호");
      }

      if (savedSections.length === 0) {
        setSaveResultMessage("변경된 내용이 없어요.");
      } else {
        setSaveResultMessage(
          `${savedSections.join(", ")} 조건을 저장했어요.${
            refreshRequired ? " 홈에서 새로운 추천을 준비하고 있어요." : ""
          }`,
        );
        setGoalsDirty(false);
        setCategoriesDirty(false);
        setPriceDirty(false);
        setVisitPlanDirty(false);
        setInitialCategories(selectedCategories);
      }
    } catch (err) {
      if (err instanceof ApiClientError && err.code === "PROFILE_VERSION_CONFLICT") {
        setSaveErrorMessage("다른 곳에서 프로파일이 먼저 바뀌었어요. 새로고침 후 다시 시도해 주세요.");
      } else {
        setSaveErrorMessage(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
      }
    } finally {
      setSaving(false);
    }
  }

  if (profileLoadState === "loading") {
    return (
      <p role="status" aria-live="polite" className="px-4 py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
        프로파일을 불러오는 중이에요...
      </p>
    );
  }

  if (profileLoadState === "error") {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-8">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {profileError}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header>
        <h1 className="text-xl font-bold">추천 조건 수정</h1>
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          목적, 주종, 가격, 남은 시간, 이동 선호를 한 번에 바꿀 수 있어요.
        </p>
      </header>

      <Section title="오늘 방문 목적">
        {goalOptionsError ? (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            {goalOptionsError}
          </p>
        ) : (
          <div className="flex flex-wrap gap-2" role="group" aria-label="방문 목적 선택">
            {goalOptions.map((option) => (
              <Chip
                key={option.code}
                label={option.label_ko}
                selected={selectedGoals.includes(option.code)}
                onClick={() => {
                  setSelectedGoals((prev) => toggleCode(prev, option.code));
                  setGoalsDirty(true);
                }}
              />
            ))}
          </div>
        )}
        <label className="flex flex-col gap-1 text-sm" htmlFor="free-text-goal">
          구체적인 목표가 있나요? (선택)
          <input
            id="free-text-goal"
            type="text"
            value={freeTextGoal}
            onChange={(event) => {
              setFreeTextGoal(event.target.value);
              setGoalsDirty(true);
            }}
            className="min-h-[44px] rounded-lg border px-3 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
        </label>
      </Section>

      <Section title="주종">
        {categoryOptionsError ? (
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            {categoryOptionsError}
          </p>
        ) : (
          <div className="flex flex-wrap gap-2" role="group" aria-label="주종 선택">
            {categoryOptions.map((option) => (
              <Chip
                key={option.code}
                label={option.label_ko}
                selected={selectedCategories.includes(option.code)}
                onClick={() => {
                  setSelectedCategories((prev) => toggleCode(prev, option.code));
                  setCategoriesDirty(true);
                }}
              />
            ))}
          </div>
        )}
      </Section>

      <Section title="가격대">
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="price-min">
            최소 가격
          </label>
          <input
            id="price-min"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="최소"
            value={priceMin}
            onChange={(event) => {
              setPriceMin(event.target.value);
              setPriceDirty(true);
            }}
            className="min-h-[44px] w-28 rounded-lg border px-3 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <span>~</span>
          <label className="sr-only" htmlFor="price-max">
            최대 가격
          </label>
          <input
            id="price-max"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="최대"
            value={priceMax}
            onChange={(event) => {
              setPriceMax(event.target.value);
              setPriceDirty(true);
            }}
            className="min-h-[44px] w-28 rounded-lg border px-3 text-base"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <span style={{ color: "var(--color-text-muted)" }}>원</span>
        </div>
      </Section>

      <Section title="남은 시간">
        <div className="flex flex-wrap gap-2" role="group" aria-label="남은 시간 선택">
          {AVAILABLE_MINUTES_PRESETS.map((preset) => (
            <Chip
              key={preset.label}
              label={preset.label}
              selected={availableMinutes === preset.value}
              onClick={() => {
                setAvailableMinutes(preset.value);
                setVisitPlanDirty(true);
              }}
            />
          ))}
        </div>
      </Section>

      <Section title="이동 선호">
        <div className="flex flex-wrap gap-2" role="group" aria-label="이동 선호 선택">
          {ROUTE_PREFERENCE_OPTIONS.map((option) => (
            <Chip
              key={option.code}
              label={option.label}
              selected={routePreference === option.code}
              onClick={() => {
                setRoutePreference(option.code);
                setVisitPlanDirty(true);
              }}
            />
          ))}
        </div>
        <div className="flex flex-col gap-2 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={minimizeDistance}
              onChange={(event) => {
                setMinimizeDistance(event.target.checked);
                setVisitPlanDirty(true);
              }}
            />
            이동 거리를 최소화해 주세요
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={accessibleRoute}
              onChange={(event) => {
                setAccessibleRoute(event.target.checked);
                setVisitPlanDirty(true);
              }}
            />
            휠체어 등 접근성 경로가 필요해요
          </label>
          <label className="flex flex-col gap-1" htmlFor="visit-date">
            방문일
            <input
              id="visit-date"
              type="date"
              value={visitDate}
              onChange={(event) => {
                setVisitDate(event.target.value);
                setVisitPlanDirty(true);
              }}
              className="min-h-[44px] w-fit rounded-lg border px-3 text-base"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
            />
          </label>
        </div>
      </Section>

      {saveErrorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {saveErrorMessage}
        </p>
      ) : null}
      {saveResultMessage ? (
        <p role="status" aria-live="polite" className="text-sm font-medium" style={{ color: "var(--color-success)" }}>
          {saveResultMessage}
        </p>
      ) : null}

      <button
        type="button"
        disabled={saving}
        onClick={handleSaveAll}
        className="tap-target sticky bottom-4 rounded-xl px-4 py-3 text-base font-bold shadow"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        {saving ? "저장 중..." : "변경사항 저장"}
      </button>
    </div>
  );
}
