import { ExhibitorDetailScreen } from "@/components/screens/ExhibitorDetailScreen";

export default function Page({ params }: { params: { id: string } }) {
  return <ExhibitorDetailScreen exhibitorId={params.id} />;
}
