const DESTINATIONS = [
  "Overview",
  "Users",
  "Usage and costs",
  "Calls",
  "Quality and operations",
  "Ask the owner assistant",
] as const;

export default function AdminHome() {
  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-6 py-16">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-glow">Owner Console</p>
        <h1 className="mt-2 text-3xl font-semibold">Skill Garden operations</h1>
      </header>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {DESTINATIONS.map((name) => (
          <li key={name} className="rounded-xl border border-white/10 bg-dusk/60 p-5">
            {name}
          </li>
        ))}
      </ul>
    </main>
  );
}
