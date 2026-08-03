"use client";

import { useState } from "react";

/**
 * 실제 회원가입을 구현하지 않는 폼 스텁 - 제출은 로컬 안내 문구만 바꾼다.
 * 실 가입·게스트 데이터 승계 로직은 W-2 §4-1 결정 및 WEB-GROUP-001 구현 이후.
 */
export function SignupStubForm() {
  const [submitted, setSubmitted] = useState(false);

  return (
    <form
      className="flex flex-col gap-4 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitted(true);
      }}
    >
      <div className="rounded-md border border-dashed border-zinc-300 bg-zinc-50 px-3 py-2 text-sm text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
        계정 전환 입력은 정식 계약 전까지 열지 않습니다.
      </div>
      <button
        type="submit"
        className="w-fit rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
      >
        회원 전환 (비활성 · Mock)
      </button>
      {submitted ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          이번 Wave에서는 실제 회원 전환을 구현하지 않습니다. 화면 흐름만 확인하는 용도입니다.
        </p>
      ) : null}
    </form>
  );
}
