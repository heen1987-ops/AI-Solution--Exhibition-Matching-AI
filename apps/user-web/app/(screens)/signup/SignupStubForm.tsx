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
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-zinc-600 dark:text-zinc-300">이메일 (자리표시자)</span>
        <input
          type="email"
          placeholder="name@example.com"
          disabled
          className="rounded-md border border-zinc-300 bg-zinc-50 px-3 py-2 text-zinc-400 dark:border-zinc-700 dark:bg-zinc-900"
        />
      </label>
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
