import { notFound } from "next/navigation";
import { AvatarDemo } from "./avatar-demo";

export const metadata = { title: "Avatar lip-sync demo" };

export default function AvatarDevPage() {
  // Dev-only harness; hidden in production builds.
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Avatar lip-sync demo</h1>
      <p className="text-sm opacity-70">
        Mock character timings stand in for ElevenLabs <code>onAudioAlignment</code>. No audio is
        played.
      </p>
      <AvatarDemo />
    </main>
  );
}
