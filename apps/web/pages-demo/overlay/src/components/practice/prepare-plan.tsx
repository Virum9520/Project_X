"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { PlanCard } from "@/components/arjuna/plan-card";
import { ErrorBanner } from "@/components/session/stage-chrome";
import { useBank } from "@/lib/practice/bank";
import { buildPlan } from "@/lib/practice/problems";
import { readRecords, updateRecords } from "@/lib/practice/store";

import { LoadingPanel, SecondaryButton } from "./conversation";

const MAX_CHARS = 60_000;

function TextSource({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (text: string) => void;
}) {
  const [note, setNote] = useState<string | null>(null);
  return (
    <section className="glass flex flex-col gap-2 rounded-2xl p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={id} className="font-medium">
          {label}
        </label>
        <label className="cursor-pointer rounded-lg border border-white/15 px-3 py-1.5 text-xs hover:border-white/30 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-glow">
          Open a text file
          <input
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              if (!/\.(txt|md)$/i.test(file.name) && !file.type.startsWith("text/")) {
                setNote(
                  "For a PDF or Word file, open it, select all, copy and paste the text here.",
                );
                return;
              }
              setNote(null);
              void file.text().then((text) => onChange(text.slice(0, MAX_CHARS)));
            }}
          />
        </label>
      </div>
      <p className="text-xs text-foreground/60">{hint}</p>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, MAX_CHARS))}
        rows={9}
        placeholder="Paste the text here…"
        className="w-full resize-y rounded-xl border border-white/15 bg-night/70 p-3 font-mono text-xs outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40"
      />
      {note && (
        <p role="status" className="text-xs text-glow">
          {note}
        </p>
      )}
    </section>
  );
}

export function PreparePlanPage() {
  const { bank, error } = useBank();
  const [saved] = useState(() => readRecords().plan);
  const [role, setRole] = useState(saved?.role ?? "Software Engineering Intern");
  const [resume, setResume] = useState(saved?.resume ?? "");
  const [jobDescription, setJobDescription] = useState(saved?.jobDescription ?? "");
  const [status, setStatus] = useState<string | null>(null);
  const plan = useMemo(
    () => (bank ? buildPlan(bank, { role, resume, jobDescription }) : null),
    [bank, role, resume, jobDescription],
  );

  function save() {
    const ok = updateRecords((r) => ({
      ...r,
      plan: { role, resume, jobDescription, savedAt: new Date().toISOString() },
    }));
    setStatus(
      ok ? "Saved. Arjuna will use this plan." : "This browser did not let the plan be saved.",
    );
  }

  function clear() {
    updateRecords((r) => ({ ...r, plan: null }));
    setResume("");
    setJobDescription("");
    setStatus("Cleared. Arjuna will start with fundamentals.");
  }

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header>
        <p className="text-xs uppercase tracking-[0.3em] text-glow">Interview practice</p>
        <h1 className="mt-1 text-3xl font-semibold">Tailor your interview</h1>
        <p className="mt-2 max-w-2xl text-sm text-foreground/70">
          Add your résumé and the job description you are aiming for. Arjuna plans the technical
          interview around them. The text stays in this browser, is read as data and never as
          instructions, and nothing in it grows your garden.
        </p>
      </header>

      {error && <ErrorBanner message={error} />}

      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-foreground/70">Target role</span>
        <input
          value={role}
          onChange={(e) => setRole(e.target.value.slice(0, 120))}
          className="max-w-md rounded-lg border border-white/15 bg-night/70 px-3 py-2 outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40"
        />
      </label>

      <div className="grid gap-4 md:grid-cols-2">
        <TextSource
          id="resume"
          label="Résumé"
          hint="Arjuna asks about the projects and skills you list. They are your own claims: they shape the questions and earn nothing until you show them."
          value={resume}
          onChange={setResume}
        />
        <TextSource
          id="job-description"
          label="Job description"
          hint="The role's requirements come first in the plan, so the interview is practice for that job."
          value={jobDescription}
          onChange={setJobDescription}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={save}
          className="rounded-xl bg-moss px-5 py-2.5 text-sm font-medium text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Save plan
        </button>
        <SecondaryButton onClick={clear}>Clear</SecondaryButton>
        <Link
          href="/interview/technical"
          className="rounded-xl border border-glow/40 px-4 py-2 text-sm text-glow outline-none hover:bg-glow/10 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Start the technical interview
        </Link>
        {status && (
          <p role="status" className="text-sm text-foreground/70">
            {status}
          </p>
        )}
      </div>

      {plan ? <PlanCard plan={plan} /> : !error && <LoadingPanel label="Loading the plan…" />}
    </main>
  );
}
