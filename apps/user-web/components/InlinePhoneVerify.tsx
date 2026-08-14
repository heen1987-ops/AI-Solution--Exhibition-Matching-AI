"use client";

import Link from "next/link";

export interface InlinePhoneVerifyProps {
  onVerified: () => void | Promise<void>;
  onCancel?: () => void;
  initialMode?: "verify" | "merge";
  title?: string;
  description?: string;
}

/**
 * Phone OTP is intentionally unavailable until its provider, abuse controls,
 * retention, and merge-confirmation contract is approved. Registered users
 * enter through the opaque one-time link delivered by the event organizer.
 */
export default function InlinePhoneVerify({
  onCancel,
  title = "사전등록 정보 연결",
}: InlinePhoneVerifyProps) {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5" aria-live="polite">
      <h2 className="font-bold text-emerald-950">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-emerald-900">
        카카오 알림톡이나 이메일로 받은 ‘나의 전시회’ 링크를 열어 주세요. 링크가 등록 정보를 서버에서 확인해 현재 기기와 안전하게 연결합니다.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Link className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white" href="/explore">
          일반 업체 검색
        </Link>
        {onCancel ? (
          <button
            type="button"
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold"
            onClick={onCancel}
          >
            닫기
          </button>
        ) : null}
      </div>
    </section>
  );
}
