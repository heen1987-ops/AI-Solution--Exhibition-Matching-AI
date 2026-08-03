import { LoadingSkeleton } from "@/components/StateViews";

export default function RecommendationsLoading() {
  return (
    <div className="flex flex-col gap-4">
      <div className="h-6 w-56 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      <LoadingSkeleton rows={3} />
    </div>
  );
}
