import { describe, expect, it } from "vitest";

import {
  buildNaverRouteUrl,
  detectNaverLaunchTarget,
  EXCO_WEST_EXHIBITION_HALL,
  NAVER_MAP_WEB_FALLBACK,
} from "./naver-map";

describe("Naver map directions", () => {
  it("uses EXCO West Wing Hall 3 as the fixed destination without collecting a start location", () => {
    const url = buildNaverRouteUrl("public", "ios", "https://match.backju.kr");

    expect(url).toContain("nmap://route/public?");
    expect(url).toContain(`dlat=${EXCO_WEST_EXHIBITION_HALL.latitude}`);
    expect(url).toContain(`dlng=${EXCO_WEST_EXHIBITION_HALL.longitude}`);
    expect(decodeURIComponent(url.replace(/\+/g, " "))).toContain(EXCO_WEST_EXHIBITION_HALL.name);
    expect(decodeURIComponent(url.replace(/\+/g, " "))).not.toContain(EXCO_WEST_EXHIBITION_HALL.eventHall);
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
    expect(NAVER_MAP_WEB_FALLBACK).toMatch(/^https:\/\/map\.naver\.com\/p\/search\//);
    expect(decodeURIComponent(NAVER_MAP_WEB_FALLBACK)).toContain(EXCO_WEST_EXHIBITION_HALL.name);
  });

  it("selects the launch target from the browser user agent", () => {
    expect(detectNaverLaunchTarget("Mozilla/5.0 (Linux; Android 15)")).toBe("android");
    expect(detectNaverLaunchTarget("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe("ios");
    expect(detectNaverLaunchTarget("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("web");
  });
});
