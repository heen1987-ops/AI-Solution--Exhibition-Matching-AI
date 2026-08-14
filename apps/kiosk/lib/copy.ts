import type { KioskLanguage } from "./types";

export const languageLabels: Record<KioskLanguage, { native: string; secondary: string }> = {
  ko: { native: "한국어", secondary: "Korean" },
  en: { native: "English", secondary: "영어" },
  ja: { native: "日本語", secondary: "일본어" },
  zh: { native: "中文", secondary: "중국어" },
};

interface Copy {
  eventFallbackName: string;
  touchToStart: string;
  privacyNote: string;
  chooseLanguage: string;
  languageHint: string;
  searchEyebrow: string;
  searchTitle: string;
  searchPlaceholder: string;
  searchButton: string;
  suggestedTitle: string;
  categoryQuickTitle: string;
  moreCategories: string;
  categoriesTitle: string;
  categoriesHint: string;
  searchWithSelected: (count: number) => string;
  resultsTitle: string;
  resultsCount: (count: number) => string;
  searchAgain: string;
  startOver: string;
  openNow: string;
  paused: string;
  waitMinutes: (minutes: number) => string;
  viewDetails: string;
  boothMap: string;
  handoffButton: string;
  handoffTitle: string;
  handoffHint: string;
  handoffExpires: string;
  productsTitle: string;
  whyRecommended: string;
  backToResults: string;
  noResultsTitle: string;
  noResultsHint: string;
  tryDifferentSearch: string;
  browseCategories: string;
  networkErrorTitle: string;
  networkErrorHint: string;
  retry: string;
  sessionEndedTitle: string;
  sessionEndedHint: string;
  backToStart: string;
  keyboardHangul: string;
  keyboardLatin: string;
  keyboardSpace: string;
  keyboardBackspace: string;
  keyboardClear: string;
  keyboardShift: string;
}

export const copy: Record<KioskLanguage, Copy> = {
  ko: {
    eventFallbackName: "2026 대한민국 백주대간",
    touchToStart: "화면을 눌러 시작하세요",
    privacyNote: "회원가입 없이 이용 · 종료 후 검색 내용이 자동으로 사라져요",
    chooseLanguage: "언어를 선택해 주세요",
    languageHint: "Please select your language",
    searchEyebrow: "오늘의 술길잡이",
    searchTitle: "어떤 업체·부스를 찾고 계세요?",
    searchPlaceholder: "예: 달지 않고 깔끔한 전통주를 찾고 있어요",
    searchButton: "검색하기",
    suggestedTitle: "이렇게도 물어보세요",
    categoryQuickTitle: "관심 분야로 빠르게 찾기",
    moreCategories: "카테고리 전체보기",
    categoriesTitle: "관심 분야를 선택해 주세요",
    categoriesHint: "여러 개를 함께 고를 수 있어요",
    searchWithSelected: (count) => (count > 0 ? `${count}개로 검색하기` : "검색하기"),
    resultsTitle: "이런 업체가 있어요",
    resultsCount: (count) => `승인된 업체 ${count}곳을 찾았어요`,
    searchAgain: "다시 검색",
    startOver: "처음으로",
    openNow: "운영 중",
    paused: "잠시 중단",
    waitMinutes: (minutes) => `약 ${minutes}분 대기`,
    viewDetails: "업체·부스 자세히 보기",
    boothMap: "부스 위치",
    handoffButton: "QR로 휴대폰에 보내기",
    handoffTitle: "휴대폰으로 이어서 보기",
    handoffHint: "카메라로 QR을 스캔해 선택한 업체 정보를 확인하세요.",
    handoffExpires: "이 QR은 잠시 후 만료됩니다.",
    productsTitle: "대표 제품",
    whyRecommended: "추천 이유",
    backToResults: "검색 결과로 돌아가기",
    noResultsTitle: "조건에 맞는 업체를 찾지 못했어요",
    noResultsHint: "다른 표현으로 다시 검색하거나 관심 분야를 선택해 보세요.",
    tryDifferentSearch: "다른 검색어로 찾기",
    browseCategories: "카테고리에서 찾기",
    networkErrorTitle: "지금은 연결할 수 없어요",
    networkErrorHint: "네트워크 상태를 확인한 뒤 다시 시도해 주세요.",
    retry: "다시 시도",
    sessionEndedTitle: "이용이 종료되었어요",
    sessionEndedHint: "검색 내용이 모두 지워졌어요. 잠시 후 처음 화면으로 돌아갑니다.",
    backToStart: "처음 화면으로",
    keyboardHangul: "한글",
    keyboardLatin: "ABC",
    keyboardSpace: "띄어쓰기",
    keyboardBackspace: "지우기",
    keyboardClear: "전체 지우기",
    keyboardShift: "쌍자음",
  },
  en: {
    eventFallbackName: "2026 Korea Backjudaegan",
    touchToStart: "Touch the screen to start",
    privacyNote: "No sign-up needed · Your search clears automatically when you finish",
    chooseLanguage: "Please choose your language",
    languageHint: "언어를 선택해 주세요",
    searchEyebrow: "Your guide today",
    searchTitle: "What exhibitor or booth are you looking for?",
    searchPlaceholder: "e.g. A clean, not-too-sweet traditional drink",
    searchButton: "Search",
    suggestedTitle: "Try asking like this",
    categoryQuickTitle: "Browse by interest",
    moreCategories: "See all categories",
    categoriesTitle: "Choose what you're interested in",
    categoriesHint: "You can pick more than one",
    searchWithSelected: (count) => (count > 0 ? `Search with ${count} selected` : "Search"),
    resultsTitle: "Here's what we found",
    resultsCount: (count) => `${count} approved exhibitors found`,
    searchAgain: "Search again",
    startOver: "Start over",
    openNow: "Open now",
    paused: "Temporarily paused",
    waitMinutes: (minutes) => `~${minutes} min wait`,
    viewDetails: "View exhibitor & booth",
    boothMap: "Booth location",
    handoffButton: "Send to phone by QR",
    handoffTitle: "Continue on your phone",
    handoffHint: "Scan the QR with your camera to view the selected exhibitor.",
    handoffExpires: "This QR expires shortly.",
    productsTitle: "Featured products",
    whyRecommended: "Why this matches",
    backToResults: "Back to results",
    noResultsTitle: "No exhibitors matched your search",
    noResultsHint: "Try a different phrase, or browse by category instead.",
    tryDifferentSearch: "Try another search",
    browseCategories: "Browse categories",
    networkErrorTitle: "Can't connect right now",
    networkErrorHint: "Please check the connection and try again.",
    retry: "Try again",
    sessionEndedTitle: "Your session has ended",
    sessionEndedHint: "Everything has been cleared. Returning to the start screen shortly.",
    backToStart: "Back to start",
    keyboardHangul: "한글",
    keyboardLatin: "ABC",
    keyboardSpace: "Space",
    keyboardBackspace: "Delete",
    keyboardClear: "Clear all",
    keyboardShift: "Shift",
  },
  ja: {
    eventFallbackName: "2026 大韓民国 白酒大幹",
    touchToStart: "画面をタッチして始めてください",
    privacyNote: "登録不要・終了後に検索内容は自動的に削除されます",
    chooseLanguage: "言語を選択してください",
    languageHint: "Please select your language",
    searchEyebrow: "本日のご案内",
    searchTitle: "どの出展社・ブースをお探しですか？",
    searchPlaceholder: "例：甘くなく、すっきりした伝統酒を探しています",
    searchButton: "検索する",
    suggestedTitle: "こんな質問もできます",
    categoryQuickTitle: "興味のある分野からすぐ探す",
    moreCategories: "カテゴリーをすべて見る",
    categoriesTitle: "興味のある分野を選んでください",
    categoriesHint: "複数選択もできます",
    searchWithSelected: (count) => (count > 0 ? `選んだ${count}件で検索` : "検索する"),
    resultsTitle: "こちらの業者が見つかりました",
    resultsCount: (count) => `承認済み業者 ${count}件が見つかりました`,
    searchAgain: "再検索",
    startOver: "最初に戻る",
    openNow: "営業中",
    paused: "一時停止",
    waitMinutes: (minutes) => `約${minutes}分待ち`,
    viewDetails: "出展社・ブースの詳細",
    boothMap: "ブース位置",
    handoffButton: "QRでスマートフォンに送る",
    handoffTitle: "スマートフォンで続きを見る",
    handoffHint: "カメラでQRを読み取り、選んだ出展社情報をご覧ください。",
    handoffExpires: "このQRはまもなく期限切れになります。",
    productsTitle: "主な商品",
    whyRecommended: "おすすめの理由",
    backToResults: "検索結果に戻る",
    noResultsTitle: "条件に合う業者が見つかりませんでした",
    noResultsHint: "別の言葉で検索するか、カテゴリーから探してみてください。",
    tryDifferentSearch: "別のキーワードで探す",
    browseCategories: "カテゴリーから探す",
    networkErrorTitle: "現在接続できません",
    networkErrorHint: "ネットワーク状態を確認してから、もう一度お試しください。",
    retry: "もう一度試す",
    sessionEndedTitle: "利用が終了しました",
    sessionEndedHint: "検索内容はすべて削除されました。まもなく最初の画面に戻ります。",
    backToStart: "最初の画面へ",
    keyboardHangul: "한글",
    keyboardLatin: "ABC",
    keyboardSpace: "スペース",
    keyboardBackspace: "削除",
    keyboardClear: "全て削除",
    keyboardShift: "シフト",
  },
  zh: {
    eventFallbackName: "2026 韩国白酒大干",
    touchToStart: "请触摸屏幕开始",
    privacyNote: "无需注册 · 结束后将自动清除搜索内容",
    chooseLanguage: "请选择语言",
    languageHint: "Please select your language",
    searchEyebrow: "今日向导",
    searchTitle: "您在寻找哪家展商或展位？",
    searchPlaceholder: "例如：想找口感清爽、不太甜的传统酒",
    searchButton: "搜索",
    suggestedTitle: "也可以这样问",
    categoryQuickTitle: "按兴趣快速查找",
    moreCategories: "查看全部分类",
    categoriesTitle: "请选择您感兴趣的分类",
    categoriesHint: "可以同时选择多个",
    searchWithSelected: (count) => (count > 0 ? `以选中的${count}项搜索` : "搜索"),
    resultsTitle: "为您找到以下展商",
    resultsCount: (count) => `找到${count}家已审核展商`,
    searchAgain: "重新搜索",
    startOver: "返回首页",
    openNow: "营业中",
    paused: "暂时休息",
    waitMinutes: (minutes) => `预计等待${minutes}分钟`,
    viewDetails: "查看展商与展位详情",
    boothMap: "展位位置",
    handoffButton: "通过二维码发送到手机",
    handoffTitle: "在手机上继续查看",
    handoffHint: "请用相机扫描二维码，查看所选展商信息。",
    handoffExpires: "此二维码将在短时间后失效。",
    productsTitle: "代表产品",
    whyRecommended: "推荐理由",
    backToResults: "返回搜索结果",
    noResultsTitle: "未找到符合条件的展商",
    noResultsHint: "请尝试其他关键词，或通过分类查找。",
    tryDifferentSearch: "换个关键词试试",
    browseCategories: "按分类查找",
    networkErrorTitle: "目前无法连接",
    networkErrorHint: "请检查网络状态后重试。",
    retry: "重试",
    sessionEndedTitle: "本次使用已结束",
    sessionEndedHint: "所有搜索内容已清除，即将返回首页。",
    backToStart: "返回首页",
    keyboardHangul: "한글",
    keyboardLatin: "ABC",
    keyboardSpace: "空格",
    keyboardBackspace: "删除",
    keyboardClear: "全部清除",
    keyboardShift: "上档",
  },
};

/** K02 검색홈의 "추천 검색문" - 카테고리와 별개로 자연어 검색을 유도하는 예시 문장. */
export const suggestedQueries: Record<KioskLanguage, string[]> = {
  ko: [
    "부드러운 막걸리 추천해 주세요",
    "선물하기 좋은 술을 찾아요",
    "도수가 낮은 술이 있나요",
    "안주랑 같이 먹기 좋은 술",
  ],
  en: [
    "Recommend a smooth makgeolli",
    "Looking for a good gift drink",
    "Something low in alcohol",
    "Pairs well with snacks",
  ],
  ja: [
    "飲みやすいマッコリを教えて",
    "贈り物に良いお酒を探しています",
    "度数が低いお酒はありますか",
    "おつまみに合うお酒",
  ],
  zh: [
    "推荐一款顺口的马格利酒",
    "想找一款适合送礼的酒",
    "有没有酒精度低一些的酒",
    "适合配下酒菜的酒",
  ],
};
