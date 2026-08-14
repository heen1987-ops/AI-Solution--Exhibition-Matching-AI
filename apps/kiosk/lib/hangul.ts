/**
 * 한글 2벌식 자모 합성 엔진 (화면 키보드용).
 *
 * 키오스크는 물리 키보드가 없는 터치스크린을 전제로 하므로, 화면에 자모 버튼을 직접
 * 배치하고(components/OnScreenKeyboard.tsx) 여기서 표준 유니코드 조합 규칙에 따라
 * 완성형 음절로 합성한다. 개인정보와 무관한 순수 텍스트 입력 유틸리티다.
 */

export const CHO = [
  "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
  "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
] as const;

export const JUNG = [
  "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
  "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
] as const;

export const JONG = [
  "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
  "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
  "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
] as const;

const DOUBLE_JONG: Record<string, string> = {
  "ㄱㅅ": "ㄳ", "ㄴㅈ": "ㄵ", "ㄴㅎ": "ㄶ", "ㄹㄱ": "ㄺ", "ㄹㅁ": "ㄻ",
  "ㄹㅂ": "ㄼ", "ㄹㅅ": "ㄽ", "ㄹㅌ": "ㄾ", "ㄹㅍ": "ㄿ", "ㄹㅎ": "ㅀ", "ㅂㅅ": "ㅄ",
};
const REVERSE_DOUBLE_JONG: Record<string, [string, string]> = {};
for (const [pair, combined] of Object.entries(DOUBLE_JONG)) {
  REVERSE_DOUBLE_JONG[combined] = [pair[0], pair[1]];
}

const DOUBLE_JUNG: Record<string, string> = {
  "ㅗㅏ": "ㅘ", "ㅗㅐ": "ㅙ", "ㅗㅣ": "ㅚ",
  "ㅜㅓ": "ㅝ", "ㅜㅔ": "ㅞ", "ㅜㅣ": "ㅟ", "ㅡㅣ": "ㅢ",
};

const CHO_INDEX = new Map<string, number>(CHO.map((c, i) => [c, i]));
const JUNG_INDEX = new Map<string, number>(JUNG.map((c, i) => [c, i]));
const JONG_INDEX = new Map<string, number>(JONG.map((c, i) => [c, i]));

function isValidJongseong(c: string): boolean {
  return CHO_INDEX.has(c) && c !== "ㄸ" && c !== "ㅃ" && c !== "ㅉ";
}

function composeSyllable(choIdx: number, jungIdx: number, jongIdx = 0): string {
  return String.fromCharCode(0xac00 + (choIdx * 21 + jungIdx) * 28 + jongIdx);
}

export interface HangulState {
  committed: string;
  cho?: number;
  jung?: number;
  jong?: number;
}

export const EMPTY_HANGUL_STATE: HangulState = { committed: "" };

export function hangulStateFromText(text: string): HangulState {
  return { committed: text };
}

function renderComposing(state: HangulState): string {
  if (state.cho === undefined) return "";
  if (state.jung === undefined) return CHO[state.cho];
  return composeSyllable(state.cho, state.jung, state.jong ?? 0);
}

export function hangulText(state: HangulState): string {
  return state.committed + renderComposing(state);
}

export function typeConsonant(state: HangulState, c: string): HangulState {
  const cIdx = CHO_INDEX.get(c);
  if (cIdx === undefined) return state;

  if (state.cho === undefined) {
    return { committed: state.committed, cho: cIdx };
  }
  if (state.jung === undefined) {
    // 초성만 있는 상태에서 자음이 또 들어옴 - 조합 불가, 앞 글자를 확정하고 새로 시작.
    return { committed: state.committed + CHO[state.cho], cho: cIdx };
  }
  if (state.jong === undefined) {
    if (isValidJongseong(c)) {
      return { committed: state.committed, cho: state.cho, jung: state.jung, jong: JONG_INDEX.get(c) };
    }
    return {
      committed: state.committed + composeSyllable(state.cho, state.jung, 0),
      cho: cIdx,
    };
  }
  // 이미 종성이 있는 상태 - 겹받침 조합을 시도한다.
  const combined = DOUBLE_JONG[JONG[state.jong] + c];
  if (combined) {
    return { committed: state.committed, cho: state.cho, jung: state.jung, jong: JONG_INDEX.get(combined) };
  }
  return {
    committed: state.committed + composeSyllable(state.cho, state.jung, state.jong),
    cho: cIdx,
  };
}

export function typeVowel(state: HangulState, v: string): HangulState {
  const vIdx = JUNG_INDEX.get(v);
  if (vIdx === undefined) return state;

  if (state.cho === undefined) {
    // 초성 없이 모음만 입력 - 독립 모음 글자로 그대로 붙인다(자동으로 'ㅇ'을 넣지 않음).
    return { committed: state.committed + v };
  }
  if (state.jung === undefined) {
    return { committed: state.committed, cho: state.cho, jung: vIdx };
  }
  if (state.jong === undefined) {
    const combined = DOUBLE_JUNG[JUNG[state.jung] + v];
    if (combined) {
      return { committed: state.committed, cho: state.cho, jung: JUNG_INDEX.get(combined) };
    }
    return {
      committed: state.committed + composeSyllable(state.cho, state.jung, 0) + v,
    };
  }
  // 종성이 있는 상태에서 모음이 들어오면 종성이 다음 글자의 초성으로 넘어간다.
  const jongChar = JONG[state.jong];
  const splitPair = REVERSE_DOUBLE_JONG[jongChar];
  if (splitPair) {
    const [keepJongChar, moveChoChar] = splitPair;
    const committed = state.committed + composeSyllable(state.cho, state.jung, JONG_INDEX.get(keepJongChar));
    return { committed, cho: CHO_INDEX.get(moveChoChar), jung: vIdx };
  }
  const committed = state.committed + composeSyllable(state.cho, state.jung, 0);
  return { committed, cho: CHO_INDEX.get(jongChar), jung: vIdx };
}

export function backspaceHangul(state: HangulState): HangulState {
  if (state.jong !== undefined) return { committed: state.committed, cho: state.cho, jung: state.jung };
  if (state.jung !== undefined) return { committed: state.committed, cho: state.cho };
  if (state.cho !== undefined) return { committed: state.committed };
  if (state.committed.length > 0) {
    return { committed: [...state.committed].slice(0, -1).join("") };
  }
  return state;
}

/** 두벌식 화면 키보드 배열. 기본/Shift 두 세트. */
export const HANGUL_ROWS: { base: string; shift?: string; kind: "cho" | "jung" }[][] = [
  [
    { base: "ㅂ", shift: "ㅃ", kind: "cho" },
    { base: "ㅈ", shift: "ㅉ", kind: "cho" },
    { base: "ㄷ", shift: "ㄸ", kind: "cho" },
    { base: "ㄱ", shift: "ㄲ", kind: "cho" },
    { base: "ㅅ", shift: "ㅆ", kind: "cho" },
    { base: "ㅛ", kind: "jung" },
    { base: "ㅕ", kind: "jung" },
    { base: "ㅑ", kind: "jung" },
    { base: "ㅐ", shift: "ㅒ", kind: "jung" },
    { base: "ㅔ", shift: "ㅖ", kind: "jung" },
  ],
  [
    { base: "ㅁ", kind: "cho" },
    { base: "ㄴ", kind: "cho" },
    { base: "ㅇ", kind: "cho" },
    { base: "ㄹ", kind: "cho" },
    { base: "ㅎ", kind: "cho" },
    { base: "ㅗ", kind: "jung" },
    { base: "ㅓ", kind: "jung" },
    { base: "ㅏ", kind: "jung" },
    { base: "ㅣ", kind: "jung" },
  ],
  [
    { base: "ㅋ", kind: "cho" },
    { base: "ㅌ", kind: "cho" },
    { base: "ㅊ", kind: "cho" },
    { base: "ㅍ", kind: "cho" },
    { base: "ㅠ", kind: "jung" },
    { base: "ㅜ", kind: "jung" },
    { base: "ㅡ", kind: "jung" },
  ],
];
