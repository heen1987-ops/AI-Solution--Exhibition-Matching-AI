import Link from "next/link";

import type { LocalPersonalizationPreview } from "@/lib/personalization-preview";
import { profileCodeLabel } from "@/lib/profile-options";
import type { ProfileView } from "@/lib/types";

function uniqueLabels(values: string[]): string[] {
  return [...new Set(values.map(profileCodeLabel))].slice(0, 8);
}

export default function PersonalizationProof({
  preview,
  profile,
}: {
  preview: LocalPersonalizationPreview | null;
  profile: ProfileView | null;
}) {
  const interests = preview?.interests ?? uniqueLabels(
    profile?.attributes
      .filter((item) => !item.attribute_code.startsWith("GOAL.") && !item.attribute_code.startsWith("BIZ_GOAL."))
      .map((item) => item.attribute_code) ?? [],
  );
  const goals = preview?.goals ?? uniqueLabels(profile?.goals.map((item) => item.attribute_code) ?? []);
  const hasSignals = interests.length > 0 || goals.length > 0;
  const personalized = Boolean(preview || profile);

  return (
    <section
      aria-labelledby="personalization-proof-heading"
      className="backju-panel border p-5 md:p-7"
      style={{ borderColor: "var(--color-border)", backgroundColor: "#fffdf8" }}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="backju-eyebrow" style={{ color: "var(--color-brand)" }}>
            MY INTERESTS
          </p>
          <h2 id="personalization-proof-heading" className="backju-section-title mt-1 text-lg font-extrabold">
            {preview ? `${preview.displayName} 님에게 적용한 기준` : "이번 추천에 적용한 기준"}
          </h2>
        </div>
        <span
          className="rounded-full px-3 py-1 text-xs font-extrabold"
          style={{
            backgroundColor: personalized ? "#cde2cd" : "#eee0b7",
            color: personalized ? "#294b2d" : "#6b5427",
          }}
        >
          {personalized ? "개인화 적용됨" : "개인화 확인 필요"}
        </span>
      </div>

      {hasSignals ? (
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-sm font-extrabold">관심분야</p>
            <ul className="mt-2 flex flex-wrap gap-2" aria-label="추천에 반영된 관심분야">
              {interests.map((label) => (
                <li key={label} className="rounded-full border border-[#cdbb92] bg-white px-3 py-1.5 text-sm font-semibold">
                  {label}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-sm font-extrabold">관람목적</p>
            <ul className="mt-2 flex flex-wrap gap-2" aria-label="추천에 반영된 관람목적">
              {goals.map((label) => (
                <li key={label} className="rounded-full border border-[#b7cfbd] bg-[#f4faf3] px-3 py-1.5 text-sm font-semibold">
                  {label}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="mt-4 text-sm leading-6" style={{ color: "var(--color-text-muted)" }}>
          개인 링크로 접속하면 사전등록에서 선택한 관심분야와 관람목적이 여기에 표시됩니다.
        </p>
      )}

      <div className="mt-5 flex flex-wrap gap-2 border-t border-[#e8dfcc] pt-4">
        <Link
          href="/profile/preferences"
          className="tap-target inline-flex rounded-full px-4 text-sm font-bold"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          반영 기준 수정
        </Link>
        <Link
          href="#catalog-explorer"
          className="tap-target inline-flex rounded-full border px-4 text-sm font-semibold"
          style={{ borderColor: "var(--color-border)" }}
        >
          원하는 업체 바로 찾기
        </Link>
      </div>
    </section>
  );
}
