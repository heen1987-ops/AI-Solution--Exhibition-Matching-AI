"use client";

/**
 * U-06 바이어 거래조건 화면.
 *
 * 근거: docs/user-ia-wireframes.md 7절 "U-06 바이어 거래조건" 와이어프레임 텍스트
 * (사업·유통 채널, 희망 제품군, 목표 가격대, 예상 거래량, 공급 희망지역, `[다음]`)와
 * "독점유통, 수출국, 상담주제, 의사결정 시점은 초기 추천에 필수인 경우만 묻고 나머지는
 * 상담 요청 시 점진적으로 수집한다"는 설명 - 그래서 이 화면은 `business_interests`,
 * `decision_timeline`, `organization_type`을 묻지 않고 빈 값으로 둔다.
 * API: 인터페이스 명세 8.3절 `PUT /api/v1/profiles/me/buyer-needs`
 * (`postAnswers({step:"BUYER_NEEDS"})`).
 *
 * 채널·제품군·공급지역은 PUBLISHED 온톨로지의 assignable concept를 사용한다.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, postAnswers, postInteraction } from "@/lib/api-client";
import { BUYER_CHANNEL_OPTIONS, PRODUCT_CATEGORY_OPTIONS, SUPPLY_REGION_OPTIONS } from "@/lib/profile-options";
import type { ExpectedOrderVolume, PriceBasis, TargetPrice } from "@/lib/types";
import { loadOnboardingState, saveOnboardingState } from "@/lib/onboarding-state";

import ChoiceChip from "../_components/ChoiceChip";
import OnboardingShell from "../_components/OnboardingShell";

type PriceBand = "UNDER_20K" | "20_50K" | "50_100K" | "OVER_100K";
const PRICE_BAND_OPTIONS: { code: PriceBand; label: string; min: number | null; max: number | null }[] = [
  { code: "UNDER_20K", label: "2만 원 이하", min: 0, max: 20000 },
  { code: "20_50K", label: "2~5만 원", min: 20000, max: 50000 },
  { code: "50_100K", label: "5~10만 원", min: 50000, max: 100000 },
  { code: "OVER_100K", label: "10만 원 이상", min: 100000, max: null },
];

const PRICE_BASIS_OPTIONS: { code: PriceBasis; label: string }[] = [
  { code: "RETAIL_PRICE", label: "소매가 기준" },
  { code: "WHOLESALE_PRICE", label: "도매가 기준" },
];

type VolumeOption = NonNullable<ExpectedOrderVolume["type"]>;
const VOLUME_OPTIONS: { code: VolumeOption; label: string }[] = [
  { code: "SAMPLE", label: "샘플" },
  { code: "SMALL_LOT", label: "소량" },
  { code: "REGULAR_SMALL", label: "정기" },
];

function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) return error.message;
  return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

export default function BuyerNeedsPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  const [channels, setChannels] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [priceBand, setPriceBand] = useState<PriceBand | null>(null);
  const [priceBasis, setPriceBasis] = useState<PriceBasis>("WHOLESALE_PRICE");
  const [volume, setVolume] = useState<VolumeOption | null>(null);
  const [regions, setRegions] = useState<string[]>([]);

  const [busy, setBusy] = useState<"next" | "skip" | "none">("none");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    const state = loadOnboardingState();
    if (!state.guestSessionId) {
      router.replace("/start");
      return;
    }
    if (state.userType !== "BUYER") {
      router.replace(state.userType === "GENERAL_VISITOR" ? "/onboarding/taste" : "/onboarding/role");
      return;
    }
    setReady(true);
  }, [router]);

  function toggle(setter: (updater: (prev: string[]) => string[]) => void, code: string) {
    setter((prev) => (prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code]));
  }

  async function submit(): Promise<boolean> {
    setErrorMessage(null);
    const band = PRICE_BAND_OPTIONS.find((option) => option.code === priceBand) ?? null;
    const targetPrice: TargetPrice | null = band
      ? { min_amount: band.min, max_amount: band.max, basis: priceBasis, currency: "KRW" }
      : null;
    const expectedOrderVolume: ExpectedOrderVolume | null = volume ? { type: volume } : null;

    try {
      const response = await postAnswers({
        step: "BUYER_NEEDS",
        data: {
          organization_type: null,
          distribution_channels: channels,
          desired_categories: categories,
          target_price: targetPrice,
          expected_order_volume: expectedOrderVolume,
          supply_regions: regions,
          business_interests: [],
          decision_timeline: null,
        },
      });
      saveOnboardingState({ profileVersion: response.profile_version, minimumProfileCompleted: true });
      return true;
    } catch (error) {
      setErrorMessage(friendlyErrorMessage(error));
      return false;
    }
  }

  async function handleSkip() {
    setBusy("skip");
    void postInteraction({
      event_type: "PROFILE_QUESTION_SKIPPED",
      screen: "ONBOARDING_BUYER_NEEDS",
      occurred_at: new Date().toISOString(),
      context: { question: "buyer_needs" },
    }).catch(() => undefined);
    router.push("/onboarding/visit-plan");
  }

  async function handleNext() {
    setBusy("next");
    const succeeded = await submit();
    setBusy("none");
    if (succeeded) router.push("/onboarding/visit-plan");
  }

  if (!ready) return null;

  return (
    <OnboardingShell title="찾고 있는 제품과 업체" stepLabel="4 / 5">
      {errorMessage ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {errorMessage}
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">사업·유통 채널</h2>
        <div className="flex flex-wrap gap-2">
          {BUYER_CHANNEL_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={channels.includes(option.code)}
              onClick={() => toggle(setChannels, option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">희망 제품군 (복수 선택)</h2>
        <div className="flex flex-wrap gap-2">
          {PRODUCT_CATEGORY_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={categories.includes(option.code)}
              onClick={() => toggle(setCategories, option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">목표 가격대</h2>
        <div className="flex flex-wrap gap-2">
          {PRICE_BAND_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={priceBand === option.code}
              onClick={() => setPriceBand(option.code)}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {PRICE_BASIS_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={priceBasis === option.code}
              onClick={() => setPriceBasis(option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">예상 거래량</h2>
        <div className="flex flex-wrap gap-2">
          {VOLUME_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={volume === option.code}
              onClick={() => setVolume(option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-bold">공급 희망지역</h2>
        <div className="flex flex-wrap gap-2">
          {SUPPLY_REGION_OPTIONS.map((option) => (
            <ChoiceChip
              key={option.code}
              label={option.label}
              selected={regions.includes(option.code)}
              onClick={() => toggle(setRegions, option.code)}
            />
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={handleSkip}
          disabled={busy !== "none"}
          className="tap-target rounded-lg px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ color: "var(--color-text-muted)" }}
        >
          건너뛰기
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={busy !== "none"}
          className="tap-target flex-1 rounded-xl px-4 py-3 text-base font-bold disabled:cursor-not-allowed disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {busy === "next" ? "저장하는 중…" : "다음"}
        </button>
      </div>
    </OnboardingShell>
  );
}
