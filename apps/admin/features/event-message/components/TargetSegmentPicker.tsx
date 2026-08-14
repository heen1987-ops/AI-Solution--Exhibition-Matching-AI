"use client";

/**
 * 타겟 세그먼트 선택기 - 작업 지시의 핵심 제약("세밀한 속성/행동 기반 타겟팅 UI 어포던스는
 * 제공하지 않는다")을 구조적으로 강제한다. `<select>`가 렌더링하는 옵션은 언제나
 * `../logic.ts`의 `TARGET_SEGMENTS` 6개뿐이고, 어떤 자유 텍스트 입력·속성 선택기·행동 필터
 * 빌더도 이 컴포넌트에 존재하지 않는다 - 새 세그먼트를 추가하려면 로직 파일과 백엔드 CHECK
 * 제약을 함께 바꿔야 하므로, 화면 조작만으로 허용목록을 우회할 방법이 없다.
 */

import Field from "@/components/Field";

import { TARGET_SEGMENT_LABEL_KO, TARGET_SEGMENTS } from "../logic";
import { TARGET_ROLE_CODES, type TargetRoleCode, type TargetSegment } from "../types";

const TARGET_ROLE_LABEL_KO: Record<TargetRoleCode, string> = {
  VISITOR: "일반 방문객",
  BUYER: "바이어",
  EXHIBITOR: "참가업체 담당자",
  OPERATOR: "운영자",
  ADMIN: "관리자",
};

export default function TargetSegmentPicker({
  segment,
  roleCode,
  onChange,
  disabled,
}: {
  segment: TargetSegment;
  roleCode: TargetRoleCode | null;
  onChange: (segment: TargetSegment, roleCode: TargetRoleCode | null) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <Field label="대상 세그먼트" required hint="코드/속성/행동 기반 세밀 타겟팅은 지원하지 않습니다.">
        <select
          aria-label="대상 세그먼트"
          className="input"
          value={segment}
          disabled={disabled}
          onChange={(e) => {
            const next = e.target.value as TargetSegment;
            onChange(next, next === "SPECIFIC_ROLE" ? (roleCode ?? "OPERATOR") : null);
          }}
        >
          {TARGET_SEGMENTS.map((s) => (
            <option key={s} value={s}>
              {TARGET_SEGMENT_LABEL_KO[s]}
            </option>
          ))}
        </select>
      </Field>

      {segment === "SPECIFIC_ROLE" && (
        <Field label="역할" required>
          <select
            aria-label="역할"
            className="input"
            value={roleCode ?? ""}
            disabled={disabled}
            onChange={(e) => onChange(segment, e.target.value as TargetRoleCode)}
          >
            {TARGET_ROLE_CODES.map((code) => (
              <option key={code} value={code}>
                {TARGET_ROLE_LABEL_KO[code]}
              </option>
            ))}
          </select>
        </Field>
      )}
    </div>
  );
}
