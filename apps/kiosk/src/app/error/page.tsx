import {
  ErrorScreen,
  type KioskErrorVariant,
} from "@/components/screens/ErrorScreen";

const VALID_VARIANTS: KioskErrorVariant[] = ["network", "qr-handoff", "generic"];

export default function Page({
  searchParams,
}: {
  searchParams: { variant?: string };
}) {
  const requested = searchParams?.variant;
  const variant: KioskErrorVariant = VALID_VARIANTS.includes(
    requested as KioskErrorVariant
  )
    ? (requested as KioskErrorVariant)
    : "generic";

  return <ErrorScreen variant={variant} />;
}
