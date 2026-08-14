"use client";

/**
 * 바이어 프로파일 화면 (WAVE 2C USER-WEB-BUYER).
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "buyer profile screen (verification status badge - read-only, buyer_type, industry,
 * interest codes, channels, order scale range, regions, cooperation types, decision
 * timeline, save/edit) with verification-status-aware messaging."
 *
 * 필드 ↔ 실제 저장 위치 매핑은 `features/buyer-profile/types.ts`/`api.ts` 상단 주석 참고.
 * 이 페이지는 `apps/user-web/app/profile/preferences/page.tsx`의 레이아웃·상태 관리
 * 패턴(로컬 Chip/Section, dirty 플래그, 저장 결과/오류 메시지)을 그대로 따른다.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ApiClientError } from "@/lib/api-client";
import type { OntologyConcept } from "@/lib/ontology";

import {
  fetchBuyerOntologyOptions,
  fetchBuyerProfile,
  saveBuyerProfile,
  type BuyerOntologyOptions,
} from "@/features/buyer-profile/api";
import {
  DECISION_TIMELINE_PRESETS,
  emptyBuyerProfileFormState,
  type BuyerProfileFormState,
} from "@/features/buyer-profile/types";
import VerificationStatusBanner from "@/features/buyer-profile/VerificationStatusBanner";
import type { BuyerVerification } from "@/features/buyer-profile/types";

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

function ConceptChipGroup({
  ariaLabel,
  options,
  selected,
  onToggle,
  emptyMessage,
}: {
  ariaLabel: string;
  options: OntologyConcept[];
  selected: string[];
  onToggle: (code: string) => void;
  emptyMessage: string;
  /** 단일/다중 선택 여부는 `onToggle`을 넘기는 호출부 로직이 결정한다 - 이 컴포넌트는
   * 렌더링·접근성 속성만 책임진다. */
  multiple: boolean;
}) {
  if (options.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        {emptyMessage}
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <Chip
          key={option.code}
          label={option.label_ko}
          selected={selected.includes(option.code)}
          onClick={() => onToggle(option.code)}
        />
      ))}
    </div>
  );
}

type LoadState = "loading" | "loaded" | "error";

export default function BuyerProfilePage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [verification, setVerification] = useState<BuyerVerification | null>(null);
  const [profileVersion, setProfileVersion] = useState<number | null>(null);
  const [ontology, setOntology] = useState<BuyerOntologyOptions | null>(null);

  const [initialForm, setInitialForm] = useState<BuyerProfileFormState>(emptyBuyerProfileFormState());
  const [form, setForm] = useState<BuyerProfileFormState>(emptyBuyerProfileFormState());
  const [editing, setEditing] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [profileData, ontologyOptions] = await Promise.all([
          fetchBuyerProfile(),
          fetchBuyerOntologyOptions(),
        ]);
        if (cancelled) return;
        setVerification(profileData.verification);
        setProfileVersion(profileData.profile.current_version);
        setInitialForm(profileData.form);
        setForm(profileData.form);
        setOntology(ontologyOptions);
        setLoadState("loaded");
      } catch (err) {
        if (cancelled) return;
        setLoadState("error");
        setLoadError(err instanceof ApiClientError ? err.message : "프로파일을 불러오지 못했습니다.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const isDirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(initialForm), [form, initialForm]);

  async function handleSave() {
    setSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const result = await saveBuyerProfile(form, initialForm);
      setProfileVersion(result.profileVersion);
      setInitialForm(form);
      setSaveMessage("바이어 정보를 저장했어요.");
      setEditing(false);
    } catch (err) {
      setSaveError(err instanceof ApiClientError ? err.message : "저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function handleCancelEdit() {
    setForm(initialForm);
    setEditing(false);
    setSaveError(null);
  }

  if (loadState === "loading") {
    return (
      <p role="status" aria-live="polite" className="px-4 py-8 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
        바이어 정보를 불러오는 중이에요...
      </p>
    );
  }

  if (loadState === "error" || !verification || !ontology) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-8">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {loadError ?? "바이어 정보를 불러오지 못했습니다."}
        </p>
      </div>
    );
  }

  const readOnly = !editing;

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-4">
      <header className="flex flex-col gap-3">
        <h1 className="text-xl font-bold">바이어 프로파일</h1>
        <VerificationStatusBanner verification={verification} />
      </header>

      <Section title="바이어 유형">
        <ConceptChipGroup
          ariaLabel="바이어 유형 선택"
          options={ontology.buyerTypes}
          selected={form.buyerTypeCode ? [form.buyerTypeCode] : []}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, buyerTypeCode: prev.buyerTypeCode === code ? null : code }));
          }}
          emptyMessage="바이어 유형 목록을 불러오지 못했어요."
          multiple={false}
        />
      </Section>

      <Section title="업종">
        <ConceptChipGroup
          ariaLabel="업종 선택"
          options={ontology.industries}
          selected={form.industryCode ? [form.industryCode] : []}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, industryCode: prev.industryCode === code ? null : code }));
          }}
          emptyMessage="업종 목록을 불러오지 못했어요."
          multiple={false}
        />
      </Section>

      <Section title="관심 목적">
        <ConceptChipGroup
          ariaLabel="관심 목적 선택"
          options={ontology.interests}
          selected={form.interestCodes}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, interestCodes: toggleCode(prev.interestCodes, code) }));
          }}
          emptyMessage="관심 목적 목록을 불러오지 못했어요."
          multiple
        />
      </Section>

      <Section title="취급 유통채널">
        <ConceptChipGroup
          ariaLabel="유통채널 선택"
          options={ontology.channels}
          selected={form.channelCodes}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, channelCodes: toggleCode(prev.channelCodes, code) }));
          }}
          emptyMessage="유통채널 목록을 불러오지 못했어요."
          multiple
        />
      </Section>

      <Section title="공급 희망 지역">
        <ConceptChipGroup
          ariaLabel="지역 선택"
          options={ontology.regions}
          selected={form.regionCodes}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, regionCodes: toggleCode(prev.regionCodes, code) }));
          }}
          emptyMessage="지역 목록을 불러오지 못했어요."
          multiple
        />
      </Section>

      <Section title="협력 형태">
        <ConceptChipGroup
          ariaLabel="협력 형태 선택"
          options={ontology.cooperationTypes}
          selected={form.cooperationTypeCodes}
          onToggle={(code) => {
            if (readOnly) return;
            setForm((prev) => ({ ...prev, cooperationTypeCodes: toggleCode(prev.cooperationTypeCodes, code) }));
          }}
          emptyMessage="협력 형태 목록을 불러오지 못했어요."
          multiple
        />
      </Section>

      <Section title="희망 주문 규모">
        <div className="flex flex-wrap gap-2" role="group" aria-label="주문 규모 유형 선택">
          {ontology.supplyCapacityTypes.map((option) => (
            <Chip
              key={option.code}
              label={option.label_ko}
              selected={form.orderScale.type === option.code}
              onClick={() => {
                if (readOnly) return;
                setForm((prev) => ({
                  ...prev,
                  orderScale: { ...prev.orderScale, type: prev.orderScale.type === option.code ? null : option.code },
                }));
              }}
            />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <label className="sr-only" htmlFor="order-scale-min">
            월 최소 수량
          </label>
          <input
            id="order-scale-min"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="최소(월)"
            disabled={readOnly}
            value={form.orderScale.monthly_units_min ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              setForm((prev) => ({
                ...prev,
                orderScale: { ...prev.orderScale, monthly_units_min: value ? Number(value) : null },
              }));
            }}
            className="min-h-[44px] w-32 rounded-lg border px-3 text-base disabled:opacity-60"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <span>~</span>
          <label className="sr-only" htmlFor="order-scale-max">
            월 최대 수량
          </label>
          <input
            id="order-scale-max"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="최대(월)"
            disabled={readOnly}
            value={form.orderScale.monthly_units_max ?? ""}
            onChange={(event) => {
              const value = event.target.value;
              setForm((prev) => ({
                ...prev,
                orderScale: { ...prev.orderScale, monthly_units_max: value ? Number(value) : null },
              }));
            }}
            className="min-h-[44px] w-32 rounded-lg border px-3 text-base disabled:opacity-60"
            style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
          />
          <span style={{ color: "var(--color-text-muted)" }}>개/월</span>
        </div>
      </Section>

      <Section title="결정 시기">
        <div className="flex flex-wrap gap-2" role="group" aria-label="결정 시기 선택">
          {DECISION_TIMELINE_PRESETS.map((preset) => (
            <Chip
              key={preset.value}
              label={preset.label}
              selected={form.decisionTimeline === preset.value}
              onClick={() => {
                if (readOnly) return;
                setForm((prev) => ({
                  ...prev,
                  decisionTimeline: prev.decisionTimeline === preset.value ? null : preset.value,
                }));
              }}
            />
          ))}
        </div>
      </Section>

      {saveError ? (
        <p role="alert" className="text-sm font-medium" style={{ color: "var(--color-danger)" }}>
          {saveError}
        </p>
      ) : null}
      {saveMessage ? (
        <p role="status" aria-live="polite" className="text-sm font-medium" style={{ color: "var(--color-success)" }}>
          {saveMessage}
        </p>
      ) : null}

      <div className="sticky bottom-4 flex gap-2">
        {editing ? (
          <>
            <button
              type="button"
              onClick={handleCancelEdit}
              disabled={saving}
              className="tap-target flex-1 rounded-xl border px-4 py-3 text-base font-bold disabled:opacity-60"
              style={{ borderColor: "var(--color-border)" }}
            >
              취소
            </button>
            <button
              type="button"
              disabled={saving || !isDirty}
              onClick={handleSave}
              className="tap-target flex-1 rounded-xl px-4 py-3 text-base font-bold shadow disabled:opacity-60"
              style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
            >
              {saving ? "저장 중..." : "저장"}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="tap-target w-full rounded-xl px-4 py-3 text-base font-bold shadow"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            정보 수정
          </button>
        )}
      </div>

      {profileVersion != null ? (
        <p className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          프로파일 버전 v{profileVersion}
        </p>
      ) : null}
    </div>
  );
}
