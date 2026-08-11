"use client";

/**
 * 알림 설정 화면의 개별 채널 토글(예: 특정 카테고리의 앱 내 알림 on/off).
 *
 * 13.2절 원칙(색상만으로 상태 구분 금지, 터치영역 44x44 이상, 키보드 조작 가능) -
 * `role="switch"` 버튼 + 텍스트 상태("켬"/"끔") + `tap-target` 유틸리티를 함께 쓴다
 * (`app/profile/preferences/page.tsx`의 `Chip` 패턴과 동일한 접근).
 */

export interface PreferenceToggleProps {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
  /** 토글 아래 보여줄 보조 설명(예: "필수 알림이라 끌 수 없어요", "이메일을 등록하면
   * 사용할 수 있어요"). */
  hint?: string;
}

export default function PreferenceToggle({ label, checked, disabled = false, onChange, hint }: PreferenceToggleProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex flex-col">
        <span className="text-sm">{label}</span>
        {hint ? (
          <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            {hint}
          </span>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={onChange}
        className="tap-target rounded-full border px-3 text-xs font-semibold"
        style={{
          borderColor: checked ? "var(--color-brand)" : "var(--color-border)",
          backgroundColor: checked ? "var(--color-brand)" : "transparent",
          color: checked ? "var(--color-brand-contrast)" : "var(--color-text-muted)",
          opacity: disabled ? 0.5 : 1,
        }}
      >
        {checked ? "켬" : "끔"}
      </button>
    </div>
  );
}
