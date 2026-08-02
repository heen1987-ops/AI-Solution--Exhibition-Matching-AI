import { MockDataBanner } from "@/components/MockDataBanner";
import { SignupStubForm } from "./SignupStubForm";

/**
 * S-8. 회원 전환. GUEST_WEB 전용 - 전환 완료 시 S-1(개인화 홈)으로 리다이렉트되고
 * 그 시점부터 S-4/S-7 접근이 열린다(W-3 §S-8). 게스트 데이터 승계 범위는 W-2 §4-1에서
 * 미결정 사항으로 남아있어 이번 Wave는 실제 회원가입/전환 로직을 구현하지 않는다
 * (AGENTS.md §11 - 범위 밖 기능 구현 금지, 실 회원가입은 금지 항목).
 */
export default function SignupPage() {
  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">회원 전환</h1>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          GUEST_WEB(키오스크에서 인계된 익명 방문객) 전용 화면입니다. 이번 Wave는 폼 UI
          골격만 제공하며, 제출해도 실제 계정이 생성되지 않습니다.
        </p>
      </header>
      <SignupStubForm />
    </div>
  );
}
