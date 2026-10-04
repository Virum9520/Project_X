import { SessionsView } from "@/components/app-pages/sessions-view";
import { getSampleGardenDataset } from "@/lib/garden/data";

export default function SessionsPage() {
  return <SessionsView dataset={getSampleGardenDataset()} isMock />;
}
