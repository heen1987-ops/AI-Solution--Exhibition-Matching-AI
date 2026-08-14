"use client";

import { useEffect, useRef, useState } from "react";

import {
  backspaceHangul,
  EMPTY_HANGUL_STATE,
  hangulStateFromText,
  hangulText,
  HANGUL_ROWS,
  type HangulState,
  typeConsonant,
  typeVowel,
} from "@/lib/hangul";
import type { KioskLanguage } from "@/lib/types";
import { copy } from "@/lib/copy";

const LATIN_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m"],
];

const KEY_CLASS =
  "min-h-tap-min min-w-tap-min rounded-xl bg-white text-xl font-medium text-stone-800 " +
  "shadow-sm ring-1 ring-stone-200 active:scale-95 active:bg-brand-100 " +
  "transition-transform dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700 " +
  "dark:active:bg-stone-700 select-none";

interface OnScreenKeyboardProps {
  language: KioskLanguage;
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
}

/** 화면 키보드. 한국어는 2벌식 한글 합성, 그 외 언어는 라틴 문자판(로마자/핀인 입력도
 * 가능)을 기본으로 하되 언제든 한글/영문 판을 전환할 수 있다. 물리 키보드가 없는
 * 키오스크 터치스크린 전제 - 모든 키가 44px 이상이다. */
export default function OnScreenKeyboard({ language, value, onChange, onSubmit }: OnScreenKeyboardProps) {
  const [mode, setMode] = useState<"hangul" | "latin">(language === "ko" ? "hangul" : "latin");
  const [shift, setShift] = useState(false);
  const [hstate, setHstate] = useState<HangulState>(hangulStateFromText(value));
  const lastEmitted = useRef(value);
  const t = copy[language];

  // 부모가 값(추천검색문 클릭, 지우기 버튼 등)을 바깥에서 바꾸면 합성 상태를 다시 맞춘다.
  useEffect(() => {
    if (value !== lastEmitted.current) {
      setHstate(hangulStateFromText(value));
    }
  }, [value]);

  function emit(nextState: HangulState) {
    const text = hangulText(nextState);
    lastEmitted.current = text;
    setHstate(nextState);
    onChange(text);
  }

  function pressHangul(base: string, shiftChar: string | undefined, kind: "cho" | "jung") {
    const char = shift && shiftChar ? shiftChar : base;
    const next = kind === "cho" ? typeConsonant(hstate, char) : typeVowel(hstate, char);
    setShift(false);
    emit(next);
  }

  function pressLatin(char: string) {
    const out = shift ? char.toUpperCase() : char;
    lastEmitted.current = value + out;
    onChange(value + out);
    setShift(false);
  }

  function pressBackspace() {
    if (mode === "hangul") {
      emit(backspaceHangul(hstate));
      return;
    }
    const next = [...value].slice(0, -1).join("");
    lastEmitted.current = next;
    onChange(next);
  }

  function pressSpace() {
    if (mode === "hangul") {
      emit({ committed: hangulText(hstate) + " " });
      return;
    }
    const next = value + " ";
    lastEmitted.current = next;
    onChange(next);
  }

  function pressClear() {
    lastEmitted.current = "";
    setHstate(EMPTY_HANGUL_STATE);
    onChange("");
  }

  return (
    <div className="w-full rounded-2xl bg-stone-100 p-3 dark:bg-stone-900 sm:p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMode("hangul")}
            className={`min-h-tap-min rounded-lg px-4 text-base font-semibold ${
              mode === "hangul"
                ? "bg-brand-600 text-white"
                : "bg-white text-stone-600 ring-1 ring-stone-300 dark:bg-stone-800 dark:text-stone-300"
            }`}
          >
            {t.keyboardHangul}
          </button>
          <button
            type="button"
            onClick={() => setMode("latin")}
            className={`min-h-tap-min rounded-lg px-4 text-base font-semibold ${
              mode === "latin"
                ? "bg-brand-600 text-white"
                : "bg-white text-stone-600 ring-1 ring-stone-300 dark:bg-stone-800 dark:text-stone-300"
            }`}
          >
            {t.keyboardLatin}
          </button>
        </div>
        <button
          type="button"
          onClick={pressClear}
          className="min-h-tap-min rounded-lg bg-white px-4 text-base text-stone-600 ring-1 ring-stone-300 dark:bg-stone-800 dark:text-stone-300"
        >
          {t.keyboardClear}
        </button>
      </div>

      {mode === "hangul" ? (
        <div className="flex flex-col gap-2">
          {HANGUL_ROWS.map((row, rowIndex) => (
            <div key={rowIndex} className="flex justify-center gap-2">
              {row.map((key) => (
                <button
                  key={key.base}
                  type="button"
                  className={KEY_CLASS + " h-14 w-14 sm:h-16 sm:w-16"}
                  onClick={() => pressHangul(key.base, key.shift, key.kind)}
                >
                  {shift && key.shift ? key.shift : key.base}
                </button>
              ))}
            </div>
          ))}
          <div className="flex justify-center gap-2">
            <button
              type="button"
              aria-pressed={shift}
              onClick={() => setShift((prev) => !prev)}
              className={KEY_CLASS + ` h-14 flex-1 sm:h-16 ${shift ? "bg-brand-100 dark:bg-stone-700" : ""}`}
            >
              {t.keyboardShift}
            </button>
            <button type="button" onClick={pressSpace} className={KEY_CLASS + " h-14 flex-[3] sm:h-16"}>
              {t.keyboardSpace}
            </button>
            <button type="button" onClick={pressBackspace} className={KEY_CLASS + " h-14 flex-1 sm:h-16"}>
              ⌫
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {LATIN_ROWS.map((row, rowIndex) => (
            <div key={rowIndex} className="flex justify-center gap-2">
              {rowIndex === 3 && (
                <button
                  type="button"
                  aria-pressed={shift}
                  onClick={() => setShift((prev) => !prev)}
                  className={KEY_CLASS + ` h-14 w-16 sm:h-16 sm:w-20 ${shift ? "bg-brand-100 dark:bg-stone-700" : ""}`}
                >
                  ⇧
                </button>
              )}
              {row.map((key) => (
                <button
                  key={key}
                  type="button"
                  className={KEY_CLASS + " h-14 w-14 sm:h-16 sm:w-16"}
                  onClick={() => pressLatin(key)}
                >
                  {shift ? key.toUpperCase() : key}
                </button>
              ))}
              {rowIndex === 3 && (
                <button
                  type="button"
                  onClick={pressBackspace}
                  className={KEY_CLASS + " h-14 w-16 sm:h-16 sm:w-20"}
                >
                  ⌫
                </button>
              )}
            </div>
          ))}
          <div className="flex justify-center gap-2">
            <button type="button" onClick={pressSpace} className={KEY_CLASS + " h-14 flex-[4] sm:h-16"}>
              {t.keyboardSpace}
            </button>
            {onSubmit && (
              <button
                type="button"
                onClick={onSubmit}
                className={KEY_CLASS + " h-14 flex-1 bg-brand-600 text-white sm:h-16"}
              >
                {t.searchButton}
              </button>
            )}
          </div>
        </div>
      )}

      {mode === "hangul" && onSubmit && (
        <div className="mt-2 flex justify-center">
          <button
            type="button"
            onClick={onSubmit}
            className={KEY_CLASS + " h-14 w-full max-w-xs bg-brand-600 text-white sm:h-16"}
          >
            {t.searchButton}
          </button>
        </div>
      )}
    </div>
  );
}
