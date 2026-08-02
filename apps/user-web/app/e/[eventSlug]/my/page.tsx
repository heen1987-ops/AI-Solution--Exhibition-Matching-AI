import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PersonalAccessLanding } from "./PersonalAccessLanding";

export const metadata: Metadata = {
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

export default async function PersonalAccessPage({
  params,
}: {
  params: Promise<{ eventSlug: string }>;
}) {
  const { eventSlug } = await params;
  if (!/^[a-z0-9-]{1,80}$/.test(eventSlug)) notFound();

  return <PersonalAccessLanding eventSlug={eventSlug} />;
}
