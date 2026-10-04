import { HomeView } from "@/components/app-pages/home-view";
import { getSampleGardenDataset } from "@/lib/garden/data";

export default function HomePage() {
  return <HomeView name="Virum" dataset={getSampleGardenDataset()} isMock />;
}
