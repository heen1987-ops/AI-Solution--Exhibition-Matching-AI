export type NaverTravelMode = "walk" | "public" | "car";
export type NaverLaunchTarget = "android" | "ios" | "web";

/**
 * EXCO 공식 시설 안내는 서관 전시장을 상위 시설로, 전시3홀을 내부 구획으로 구분한다.
 * 네이버 지도에는 검색 가능한 서관 전시장을 목적지로 전달하고 3홀은 행사장 안내에만 쓴다.
 */
export const EXCO_WEST_EXHIBITION_HALL = {
  name: "EXCO 서관 전시장",
  eventHall: "서관 1층 3홀",
  address: "대구광역시 북구 엑스코로 10",
  latitude: 35.9071678,
  longitude: 128.6130954,
  naverPlaceId: "11566331",
} as const;

export const NAVER_MAP_WEB_FALLBACK = `https://map.naver.com/p/search/${encodeURIComponent(EXCO_WEST_EXHIBITION_HALL.name)}`;

const ROUTE_PATH: Record<NaverTravelMode, string> = {
  walk: "route/walk",
  public: "route/public",
  car: "route/car",
};

function routeQuery(appName: string): string {
  const query = new URLSearchParams({
    dlat: String(EXCO_WEST_EXHIBITION_HALL.latitude),
    dlng: String(EXCO_WEST_EXHIBITION_HALL.longitude),
    dname: EXCO_WEST_EXHIBITION_HALL.name,
    appname: appName,
  });

  // 출발 좌표를 의도적으로 넣지 않는다. 네이버 지도 공식 규격에 따라 네이버 앱이
  // 사용자의 현재 위치를 출발지로 사용하며, 우리 웹은 위치정보를 수집하지 않는다.
  return query.toString();
}

export function buildNaverRouteUrl(
  mode: NaverTravelMode,
  launchTarget: NaverLaunchTarget,
  appName: string,
): string {
  if (launchTarget === "web") return NAVER_MAP_WEB_FALLBACK;

  const path = ROUTE_PATH[mode];
  const query = routeQuery(appName);

  if (launchTarget === "android") {
    return `intent://${path}?${query}#Intent;scheme=nmap;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.nhn.android.nmap;end`;
  }

  return `nmap://${path}?${query}`;
}

export function detectNaverLaunchTarget(userAgent: string): NaverLaunchTarget {
  if (/android/i.test(userAgent)) return "android";
  if (/iphone|ipad|ipod/i.test(userAgent)) return "ios";
  return "web";
}
