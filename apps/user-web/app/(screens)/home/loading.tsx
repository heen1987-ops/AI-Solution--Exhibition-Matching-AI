import { LoadingSkeleton } from "@/components/StateViews";

export default function HomeLoading() {
  return (
    <div className="flex flex-col gap-4">
      <div className="h-6 w-40 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <LoadingSkeleton rows={2} />
    </div>
  );
}
