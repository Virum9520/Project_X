import { GardenDashboard } from "@/components/garden/dashboard";
import { getSampleGardenDataset } from "@/lib/garden/data";
import { parseState } from "@/lib/garden/state";

export default function GardenPage() {
  const dataset = getSampleGardenDataset();
  return <GardenDashboard dataset={dataset} initialState={parseState({}, dataset)} isMock />;
}
