import Link from "next/link";

const NAV_LINKS = [
  { href: "/", label: "준비 화면" },
  { href: "/console", label: "운영 콘솔(예정 목록)" },
  { href: "/health", label: "상태" },
] as const;

export function NavBar() {
  return (
    <header className="border-b border-black/10 bg-white/70 backdrop-blur dark:border-white/10 dark:bg-black/30">
      <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
        <span className="text-sm font-semibold tracking-tight text-accent">
          백주대간 관리자 (Admin) - 스켈레톤
        </span>
        <nav className="flex gap-4 text-sm">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-slate-600 transition-colors hover:text-accent dark:text-slate-300"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
