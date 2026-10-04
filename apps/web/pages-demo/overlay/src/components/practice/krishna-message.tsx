"use client";

import type { GardenDataset } from "@sg/contracts";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { CharacterAvatar } from "@/components/character/character-avatar";
import { DAY_MS, plantsAt, readiness, stageRank } from "@/lib/garden/derive";
import { DEFAULT_STATE } from "@/lib/garden/state";
import { lowerFirst } from "@/lib/practice/coach-lines";
import { usePracticeDataset } from "@/lib/practice/dataset";
import { useCoachVoice } from "@/lib/practice/speech";

import { PrimaryButton, SecondaryButton, VoiceToggle } from "./conversation";

const NOTE_KEY = "sg.future-self.note";
const MAX_NOTE_SECONDS = 60;

interface VoiceNote {
  dataUrl: string;
  createdAt: string;
  seconds: number;
}

/** Today's message, written from the learner's own garden; the same all day. */
function todaysMessage(dataset: GardenDataset): string[] {
  const now = Date.parse(dataset.generatedAt);
  const day = Math.floor(now / DAY_MS);
  const choose = <T,>(items: T[]) => items[day % items.length]!;
  const plants = plantsAt(dataset, DEFAULT_STATE.filters, now);
  const score = Math.round(readiness(dataset, plants).overall);
  const recent = [...dataset.growthEvents]
    .reverse()
    .find(
      (g) =>
        now - Date.parse(g.occurredAt) < 7 * DAY_MS &&
        dataset.evidence.find((e) => e.id === g.evidenceIds[0])?.kind === "independent",
    );
  const title = new Map(dataset.plants.map((p) => [p.key, p.title]));
  const best = [...plants].sort((a, b) => stageRank(b.stage) - stageRank(a.stage))[0];
  const next = dataset.nextBest[0];
  const lines = [
    choose([
      "Hey. It's you, six months from now.",
      "Hi. It's me. Well, you, a bit further along.",
      "Hey, it's future you. I don't have long, so listen.",
    ]),
    dataset.streakDays > 1
      ? `You're on a ${dataset.streakDays}-day streak right now. I remember how ordinary those days felt. They weren't.`
      : "I know starting again feels heavy. One short session is all it takes.",
    recent
      ? `What you showed on ${title.get(recent.plantKey)?.toLowerCase() ?? "that topic"} this week, on your own? That's when it clicked. I still lean on it.`
      : best && best.stage !== "unassessed"
        ? `${best.meta.title} is your strongest plant. Interviews will ask about it, and you'll be calm.`
        : "",
    next ? `Today: ${lowerFirst(next.title)}. ${next.reason}` : "",
    score < 50
      ? `You're at ${score}% readiness. Mine is a lot higher, and every point came from days like today.`
      : `You're past halfway, at ${score}%. Don't coast now.`,
    choose([
      "Keep going. I'm proof it works.",
      "You don't have to be fast. Just keep showing up.",
      "I'm proud of you. Now go practise.",
    ]),
  ];
  return lines.filter(Boolean);
}

function readNote(): VoiceNote | null {
  try {
    const raw = window.localStorage.getItem(NOTE_KEY);
    return raw ? (JSON.parse(raw) as VoiceNote) : null;
  } catch {
    return null;
  }
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}

export function KrishnaPage() {
  const dataset = usePracticeDataset();
  const message = useMemo(() => todaysMessage(dataset), [dataset]);
  const voice = useCoachVoice("krishna");
  const [line, setLine] = useState<number | null>(null);
  const playing = useRef(false);

  async function play() {
    if (playing.current) {
      playing.current = false;
      voice.silence();
      setLine(null);
      return;
    }
    playing.current = true;
    for (const [i, text] of message.entries()) {
      if (!playing.current) break;
      setLine(i);
      await voice.say(text);
    }
    playing.current = false;
    setLine(null);
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 pb-16 pt-32">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm uppercase tracking-[0.3em] text-glow">Krishna · Future self</p>
          <h1 className="mt-2 text-3xl font-semibold">A message from your future self</h1>
          <p className="mt-3 text-foreground/70">
            Every day Krishna writes you a short message from the person you are becoming, built
            from what you actually practised.
          </p>
        </div>
        <VoiceToggle />
      </header>

      <section className="glass flex flex-col gap-5 rounded-2xl p-6 sm:flex-row sm:items-start">
        <div className="shrink-0 self-center">
          <CharacterAvatar character="krishna" size={150} driver={voice.lipSync} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-[0.22em] text-foreground/50">
            Today&apos;s message ·{" "}
            {new Date(dataset.generatedAt).toLocaleDateString("en-US", {
              weekday: "long",
              month: "short",
              day: "numeric",
            })}
          </p>
          <div className="mt-3 flex flex-col gap-2 text-base leading-relaxed">
            {message.map((text, i) => (
              <p
                key={i}
                className={`transition-colors ${line === null || line === i ? "text-foreground" : "text-foreground/45"}`}
              >
                {text}
              </p>
            ))}
          </div>
          <div className="mt-4">
            <PrimaryButton tone="moss" onClick={() => void play()}>
              {line === null ? "Hear today's message" : "Stop"}
            </PrimaryButton>
          </div>
        </div>
      </section>

      <VoiceNoteCard />

      <section className="rounded-xl border border-white/10 bg-dusk/60 p-6 text-sm text-foreground/75">
        <h2 className="font-medium text-foreground">Your own voice</h2>
        <p className="mt-2">
          Krishna can speak these messages in a copy of your own voice. That copy is only ever made
          after you read a fresh consent phrase aloud and it is checked, it is used for nothing
          else, and one tap deletes it along with your recording.
        </p>
        <p className="mt-2">
          Want to hear what you sound like when you&apos;re confident?{" "}
          <Link href="/session" className="text-glow underline underline-offset-2">
            Explain a concept to Drona
          </Link>{" "}
          out loud.
        </p>
      </section>
    </main>
  );
}

function VoiceNoteCard() {
  // This page renders only in the browser, so storage can be read up front.
  const [note, setNote] = useState<VoiceNote | null>(readNote);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const started = useRef(0);

  useEffect(() => {
    if (!recording) return;
    const id = window.setInterval(() => {
      const s = Math.floor((Date.now() - started.current) / 1000);
      setSeconds(s);
      if (s >= MAX_NOTE_SECONDS) recorder.current?.stop();
    }, 250);
    return () => window.clearInterval(id);
  }, [recording]);

  async function start() {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("This browser can't record audio.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
        const reader = new FileReader();
        reader.onload = () => {
          const saved: VoiceNote = {
            dataUrl: String(reader.result),
            createdAt: new Date().toISOString(),
            seconds: Math.max(1, Math.round((Date.now() - started.current) / 1000)),
          };
          try {
            window.localStorage.setItem(NOTE_KEY, JSON.stringify(saved));
          } catch {
            setError(
              "The note is too large to keep in this browser; it will play until you leave.",
            );
          }
          setNote(saved);
        };
        reader.readAsDataURL(blob);
      };
      recorder.current = rec;
      started.current = Date.now();
      setSeconds(0);
      rec.start();
      setRecording(true);
    } catch {
      setError("Microphone access was not allowed.");
    }
  }

  function remove() {
    try {
      window.localStorage.removeItem(NOTE_KEY);
    } catch {
      // Nothing stored.
    }
    setNote(null);
  }

  return (
    <section className="rounded-xl border border-white/10 bg-dusk/60 p-6">
      <h2 className="font-medium">A note in your own voice</h2>
      <p className="mt-2 text-sm text-foreground/70">
        Record up to a minute for the future you: why you started, what you want to remember. It
        stays in this browser and is never uploaded.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-ember">
          {error}
        </p>
      )}
      {note && !recording && (
        <figure className="mt-4 flex flex-col gap-2">
          <audio controls src={note.dataUrl} className="w-full" />
          <figcaption className="text-xs text-foreground/50">
            Recorded{" "}
            {new Date(note.createdAt).toLocaleDateString("en-US", {
              month: "short",
              day: "numeric",
            })}{" "}
            · {note.seconds}s
          </figcaption>
        </figure>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {recording ? (
          <PrimaryButton tone="ember" onClick={() => recorder.current?.stop()}>
            Stop recording ({seconds}s)
          </PrimaryButton>
        ) : (
          <PrimaryButton tone="moss" onClick={() => void start()}>
            {note ? "Record a new note" : "Record a note"}
          </PrimaryButton>
        )}
        {note && !recording && <SecondaryButton onClick={remove}>Delete note</SecondaryButton>}
      </div>
    </section>
  );
}
