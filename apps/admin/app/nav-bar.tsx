import Link from "next/link";

const NAV_LINKS = [
  { href: "/", label: "운영 화면" },
  { href: "/console", label: "운영 콘솔" },
  { href: "/health", label: "상태" },
] as const;

export function NavBar() {
  return (
    <header className="border-b border-black/10 bg-white/70 backdrop-blur dark:border-white/10 dark:bg-black/30">
      <div className="mx-auto flex max-w-4xl flex-col gap-3 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <span className="whitespace-nowrap text-sm font-semibold tracking-tight text-accent">
          백주대간 관리자
        </span>
        <nav className="flex flex-wrap gap-2 text-sm">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="whitespace-nowrap rounded-md px-2 py-1 text-slate-600 transition-colors hover:bg-slate-100 hover:text-accent dark:text-slate-300 dark:hover:bg-white/10"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
