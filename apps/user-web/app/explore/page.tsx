import CatalogExplorer from "@/components/CatalogExplorer";

export default function ExplorePage() {
  return (
    <div className="mx-auto max-w-screen-content space-y-5 px-4 py-5 md:py-6">
      <CatalogExplorer />
      <p className="backju-asset-credit -mt-3 text-right">
        행사 이미지 출처: {" "}
        <a href="https://www.backju.kr/" target="_blank" rel="noreferrer">
          대한민국 백주대간 공식 홈페이지
        </a>
      </p>
      <p className="pb-2 text-center text-xs" style={{ color: "var(--color-text-muted)" }}>
        앱 설치나 전용 키오스크 없이 현재 브라우저에서 계속 이용할 수 있습니다.
      </p>
    </div>
  );
}
