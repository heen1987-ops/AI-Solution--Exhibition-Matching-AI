import { ScreenNav } from "@/components/ScreenNav";

/**
 * S-1~S-8 화면 공통 셸. docs/redesign-v2/web/W-3-screen-ia.md의 화면 인벤토리를
 * 한 화면씩 오가며 확인할 수 있도록 상단 네비게이션만 제공한다(레이아웃 세부 디자인은
 * 이번 Wave 범위 밖).
 */
export default function ScreensLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <ScreenNav />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
