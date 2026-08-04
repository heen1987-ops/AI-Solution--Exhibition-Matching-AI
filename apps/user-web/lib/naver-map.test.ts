import { describe, expect, it } from "vitest";

import {
  buildNaverMapScriptUrl,
  buildNaverRouteUrl,
  detectNaverLaunchTarget,
  EXCO_HALL_3,
  NAVER_MAP_WEB_FALLBACK,
} from "./naver-map";

describe("Naver map directions", () => {
  it("loads the official Web Dynamic Map SDK with the Web SDK ncpKeyId", () => {
    expect(buildNaverMapScriptUrl("public key")).toBe(
      "https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=public%20key",
    );
  });

  it("does not allow additional query parameters through the public key", () => {
    expect(buildNaverMapScriptUrl("key&submodules=geocoder")).toBe(
      "https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=key%26submodules%3Dgeocoder",
    );
  });

  it("uses EXCO West Wing Hall 3 as the fixed destination without collecting a start location", () => {
    const url = buildNaverRouteUrl("public", "ios", "https://match.backju.kr");

    expect(url).toContain("nmap://route/public?");
    expect(url).toContain(`dlat=${EXCO_HALL_3.latitude}`);
    expect(url).toContain(`dlng=${EXCO_HALL_3.longitude}`);
    expect(decodeURIComponent(url.replace(/\+/g, " "))).toContain(EXCO_HALL_3.name);
    expect(url).not.toContain("slat=");
    expect(url).not.toContain("slng=");
  });

  it("uses the Android intent form required for mobile web", () => {
    const url = buildNaverRouteUrl("car", "android", "https://match.backju.kr");

    expect(url).toContain("intent://route/car?");
    expect(url).toContain("package=com.nhn.android.nmap");
    expect(url).toContain("scheme=nmap");
  });

  it("supports the official walking route action", () => {
    expect(buildNaverRouteUrl("walk", "ios", "https://match.backju.kr")).toContain("nmap://route/walk?");
  });

  it("falls back to a Naver Map web search on desktop", () => {
    expect(buildNaverRouteUrl("car", "web", "https://match.backju.kr")).toBe(NAVER_MAP_WEB_FALLBACK);
  });

  it("selects the launch target from the browser user agent", () => {
    expect(detectNaverLaunchTarget("Mozilla/5.0 (Linux; Android 15)")).toBe("android");
    expect(detectNaverLaunchTarget("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe("ios");
    expect(detectNaverLaunchTarget("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("web");
  });
});
