"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { buildNaverMapScriptUrl, EXCO_HALL_3, NAVER_MAP_WEB_FALLBACK } from "@/lib/naver-map";

type MapStatus = "loading" | "ready" | "unconfigured" | "error";
type LocationStatus = "idle" | "locating" | "visible" | "denied" | "error";

type NaverLatLng = object;

interface NaverMapInstance {
  fitBounds(bounds: object, padding?: object): void;
  setCenter(position: NaverLatLng): void;
  setZoom(zoom: number): void;
}

interface NaverMarkerInstance {
  setMap(map: NaverMapInstance | null): void;
}

interface NaverLatLngBoundsInstance {
  extend(position: NaverLatLng): NaverLatLngBoundsInstance;
}

interface NaverMapsNamespace {
  LatLng: new (latitude: number, longitude: number) => NaverLatLng;
  LatLngBounds: new () => NaverLatLngBoundsInstance;
  Map: new (
    element: HTMLElement,
    options: {
      center: NaverLatLng;
      zoom: number;
      minZoom?: number;
      zoomControl?: boolean;
      mapDataControl?: boolean;
      scaleControl?: boolean;
    },
  ) => NaverMapInstance;
  Marker: new (options: {
    position: NaverLatLng;
    map: NaverMapInstance;
    title?: string;
  }) => NaverMarkerInstance;
}

declare global {
  interface Window {
    naver?: { maps?: NaverMapsNamespace };
  }
}

let naverMapLoadPromise: Promise<void> | null = null;
const NAVER_MAP_LOAD_TIMEOUT_MS = 10_000;

function loadNaverMapScript(ncpKeyId: string): Promise<void> {
  if (window.naver?.maps) return Promise.resolve();
  if (naverMapLoadPromise) return naverMapLoadPromise;

  naverMapLoadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-meet-ai-naver-map]");
    // 인증 실패나 중단된 이전 요청의 script가 남아 있으면 load 이벤트가 다시 발생하지
    // 않는다. 재시도가 멈추지 않도록 새 요청 전에 제거한다.
    existing?.remove();

    const script = document.createElement("script");
    script.src = buildNaverMapScriptUrl(ncpKeyId);
    script.async = true;
    script.defer = true;
    script.dataset.meetAiNaverMap = "true";

    let settled = false;
    const timeoutId = window.setTimeout(() => fail("NAVER_MAP_LOAD_TIMEOUT"), NAVER_MAP_LOAD_TIMEOUT_MS);

    function cleanup() {
      window.clearTimeout(timeoutId);
      script.removeEventListener("load", handleLoad);
      script.removeEventListener("error", handleError);
    }

    function succeed() {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    }

    function fail(code: string) {
      if (settled) return;
      settled = true;
      cleanup();
      script.remove();
      reject(new Error(code));
    }

    function handleLoad() {
      if (window.naver?.maps) succeed();
      else fail("NAVER_MAP_SDK_UNAVAILABLE");
    }

    function handleError() {
      fail("NAVER_MAP_LOAD_FAILED");
    }

    script.addEventListener("load", handleLoad, { once: true });
    script.addEventListener("error", handleError, { once: true });
    document.head.appendChild(script);
  }).catch((error) => {
    naverMapLoadPromise = null;
    throw error;
  });

  return naverMapLoadPromise;
}

function locationMessage(status: LocationStatus): string {
  switch (status) {
    case "locating":
      return "현재 위치를 확인하고 있어요.";
    case "visible":
      return "현재 위치와 행사장을 지도에 함께 표시했습니다.";
    case "denied":
      return "위치 권한이 꺼져 있어 행사장 위치만 표시합니다.";
    case "error":
      return "현재 위치를 확인하지 못했어요. 행사장 위치는 계속 볼 수 있습니다.";
    default:
      return "버튼을 누를 때만 현재 위치 권한을 요청합니다.";
  }
}

export default function NaverVenueMap() {
  const ncpKeyId = process.env.NEXT_PUBLIC_NAVER_MAP_NCP_KEY_ID?.trim() ?? "";
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<NaverMapInstance | null>(null);
  const venueMarkerRef = useRef<NaverMarkerInstance | null>(null);
  const locationMarkerRef = useRef<NaverMarkerInstance | null>(null);
  const [mapStatus, setMapStatus] = useState<MapStatus>(ncpKeyId ? "loading" : "unconfigured");
  const [locationStatus, setLocationStatus] = useState<LocationStatus>("idle");
  const [loadAttempt, setLoadAttempt] = useState(0);

  const initializeMap = useCallback(() => {
    const maps = window.naver?.maps;
    const container = containerRef.current;
    if (!maps || !container) throw new Error("NAVER_MAP_SDK_UNAVAILABLE");

    const venue = new maps.LatLng(EXCO_HALL_3.latitude, EXCO_HALL_3.longitude);
    const map = new maps.Map(container, {
      center: venue,
      zoom: 17,
      minZoom: 7,
      zoomControl: true,
      mapDataControl: true,
      scaleControl: true,
    });

    const venueMarker = new maps.Marker({
      position: venue,
      map,
      title: EXCO_HALL_3.name,
    });

    mapRef.current = map;
    venueMarkerRef.current = venueMarker;
    setMapStatus("ready");
  }, []);

  useEffect(() => {
    if (!ncpKeyId) {
      setMapStatus("unconfigured");
      return;
    }

    let cancelled = false;
    setMapStatus("loading");

    loadNaverMapScript(ncpKeyId)
      .then(() => {
        if (!cancelled) initializeMap();
      })
      .catch(() => {
        if (!cancelled) setMapStatus("error");
      });

    return () => {
      cancelled = true;
      locationMarkerRef.current?.setMap(null);
      venueMarkerRef.current?.setMap(null);
      locationMarkerRef.current = null;
      venueMarkerRef.current = null;
      mapRef.current = null;
    };
  }, [initializeMap, loadAttempt, ncpKeyId]);

  const retryMap = () => {
    naverMapLoadPromise = null;
    setMapStatus("loading");
    setLoadAttempt((attempt) => attempt + 1);
  };

  const showCurrentLocation = () => {
    const maps = window.naver?.maps;
    const map = mapRef.current;
    if (!maps || !map || !navigator.geolocation) {
      setLocationStatus("error");
      return;
    }

    setLocationStatus("locating");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const current = new maps.LatLng(coords.latitude, coords.longitude);
        const venue = new maps.LatLng(EXCO_HALL_3.latitude, EXCO_HALL_3.longitude);

        locationMarkerRef.current?.setMap(null);
        locationMarkerRef.current = new maps.Marker({
          position: current,
          map,
          title: "현재 위치",
        });

        const bounds = new maps.LatLngBounds();
        bounds.extend(current).extend(venue);
        map.fitBounds(bounds, { top: 56, right: 36, bottom: 56, left: 36 });
        setLocationStatus("visible");
      },
      (error) => {
        setLocationStatus(error.code === error.PERMISSION_DENIED ? "denied" : "error");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 30000 },
    );
  };

  return (
    <div className="naver-map-shell" aria-label="네이버 지도 대구 EXCO 서관 3홀 위치">
      <div ref={containerRef} className="naver-map-canvas" aria-hidden={mapStatus !== "ready"} />

      {mapStatus === "loading" ? (
        <div className="naver-map-state" role="status">
          <span className="naver-map-n">N</span>
          <strong>네이버 지도를 불러오는 중입니다.</strong>
        </div>
      ) : null}

      {mapStatus === "unconfigured" ? (
        <div className="naver-map-state naver-map-state-config" role="status">
          <span className="naver-map-n">N</span>
          <div>
            <strong>행사장 지도를 준비하고 있습니다.</strong>
            <p>아래 길찾기 버튼이나 네이버 지도 링크로 EXCO 3홀 위치를 확인할 수 있습니다.</p>
          </div>
        </div>
      ) : null}

      {mapStatus === "error" ? (
        <div className="naver-map-state" role="alert">
          <span className="naver-map-n">N</span>
          <div>
            <strong>네이버 지도를 바로 표시하지 못했습니다.</strong>
            <p>다시 시도하거나 네이버 지도에서 행사장을 확인해 주세요.</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={retryMap}
                className="tap-target rounded-sm border border-brand-300 bg-white px-4 text-sm font-extrabold text-brand-700"
              >
                지도 다시 불러오기
              </button>
              <a
                href={NAVER_MAP_WEB_FALLBACK}
                target="_blank"
                rel="noreferrer"
                className="tap-target rounded-sm border border-[var(--color-border)] bg-white px-4 text-sm font-bold text-[#4d4a43]"
              >
                네이버 지도에서 보기
              </a>
            </div>
          </div>
        </div>
      ) : null}

      {mapStatus === "ready" ? (
        <div className="naver-map-control-panel">
          <div>
            <strong>{EXCO_HALL_3.name}</strong>
            <span>{EXCO_HALL_3.address}</span>
          </div>
          <button
            type="button"
            onClick={showCurrentLocation}
            disabled={locationStatus === "locating"}
            className="tap-target rounded-sm bg-white px-4 font-extrabold text-brand-700 shadow-md disabled:cursor-wait disabled:opacity-70"
          >
            내 위치 함께 보기
          </button>
        </div>
      ) : null}

      {mapStatus === "ready" ? (
        <p className="naver-map-location-status" aria-live="polite">
          {locationMessage(locationStatus)}
        </p>
      ) : null}
    </div>
  );
}
