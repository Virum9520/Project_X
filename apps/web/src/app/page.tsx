import { DIMENSION_TO_PART, PLANT_STAGES, type Character } from "@sg/contracts";
import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

import { SectionLink } from "@/components/section-link";
import { SproutMark } from "@/components/site-nav";

import { BackToTop } from "./_landing/back-to-top";
import { CountUp } from "./_landing/count-up";
import { LazyHeroScene } from "./_landing/hero-scene-lazy";
import {
  GrowIllustration,
  ProveIllustration,
  RetainIllustration,
  TalkIllustration,
} from "./_landing/illustrations";
import { RevealBlock, RevealText } from "./_landing/reveal";
import { ScrollReset } from "./_landing/scroll-reset";

const MENTORS: { id: Character; role: string; line: string; color: string }[] = [
  {
    id: "drona",
    role: "Teacher",
    line: "Teaches, then has you teach it back",
    color: "var(--moss)",
  },
  {
    id: "arjuna",
    role: "Technical interviewer",
    line: "Live coding with tests that run",
    color: "var(--glow)",
  },
  {
    id: "vidura",
    role: "HR interviewer",
    line: "Behavioral and panel rounds",
    color: "var(--bloom)",
  },
  {
    id: "bhima",
    role: "Accountability",
    line: "Calls when you said you'd practice",
    color: "#f2a65a",
  },
  {
    id: "krishna",
    role: "Guide",
    line: "Your goals, in your future self's voice",
    color: "#b9a6ff",
  },
  { id: "sanjaya", role: "Narrator", line: "A weekly cinematic recap", color: "#e8ecf6" },
];

const CONCEPTS = [
  "Big-O",
  "Hash maps",
  "Recursion",
  "Binary search",
  "Two pointers",
  "Sliding window",
  "Trees",
  "Heaps",
  "Graphs",
  "Union-find",
  "Tries",
  "Dynamic programming",
  "Concurrency",
  "Databases",
  "Networking",
  "OS scheduling",
  "System design",
  "STAR stories",
];

const STEPS = [
  {
    title: "Talk",
    body: "Voice sessions with a mentor who starts from what you already know, not from page one.",
    art: <TalkIllustration />,
  },
  {
    title: "Prove",
    body: "Explain it back. Cross-questions and teach-backs turn answers into evidence, with hints tracked.",
    art: <ProveIllustration />,
  },
  {
    title: "Grow",
    body: "A deterministic, versioned rules engine decides growth. The same evidence always grows the same plant.",
    art: <GrowIllustration />,
  },
  {
    title: "Retain",
    body: "Spaced reviews and check-in calls keep skills from wilting after the exam is over.",
    art: <RetainIllustration />,
  },
];

const DIMENSION_COPY: Record<keyof typeof DIMENSION_TO_PART, string> = {
  explanation: "Can you say why it works, in your own words?",
  application: "Can you use it on a problem you haven't seen?",
  transfer: "Can you carry it into a different domain?",
  retention: "Is it still there next week, and next month?",
};

const PRINCIPLES = [
  {
    title: "Every leaf cites evidence",
    body: "Click any plant and see the exact moments in your sessions that grew it.",
  },
  {
    title: "Assisted is not independent",
    body: "Answers you reached with hints are tracked apart from answers you reached alone.",
  },
  {
    title: "Rules, not vibes",
    body: "Progression comes from a versioned rules engine you can replay, not a model's mood.",
  },
  {
    title: "Your documents are data",
    body: "Uploaded notes and résumés inform your mentors. They never get to give them orders.",
  },
];

const PRACTICE = [
  "Data structures",
  "Algorithms",
  "System design",
  "Mock technical interviews",
  "Behavioral interviews",
  "Résumé-tailored questions",
  "Operating systems",
  "Databases",
  "Networking",
];

export default function Home() {
  return (
    <>
      <ScrollReset />
      <IntroCurtain />
      <main className="flex flex-1 flex-col">
        <Hero />
        <Mentors />
        <HowItWorks />
        <GardenDashboard />
        <Principles />
        <Practice />
        <FinalCta />
      </main>
      <Footer />
      <BackToTop />
    </>
  );
}

function IntroCurtain() {
  return (
    <div
      aria-hidden
      className="intro-curtain pointer-events-none fixed inset-0 z-[60] grid place-items-center bg-night"
    >
      <p className="text-[clamp(2.5rem,11vw,9rem)] font-semibold tracking-[0.12em] text-foreground">
        {"SKILL GARDEN".split("").map((ch, i) => (
          <span key={i} className="intro-letter" style={{ "--i": i } as CSSProperties}>
            {ch === " " ? " " : ch}
          </span>
        ))}
      </p>
    </div>
  );
}

function Hero() {
  return (
    <section className="relative isolate flex min-h-[100svh] items-end overflow-hidden pb-16 pt-[52svh] lg:items-center lg:pb-24 lg:pt-32">
      <div
        aria-hidden
        className="absolute inset-0 -z-20"
        style={{
          background:
            "radial-gradient(60% 55% at 72% 42%, rgb(63 174 122 / 0.22), transparent 70%), radial-gradient(40% 40% at 88% 75%, rgb(244 184 212 / 0.14), transparent 70%), radial-gradient(45% 45% at 60% 15%, rgb(155 231 255 / 0.12), transparent 70%)",
        }}
      />
      <div className="absolute inset-x-0 top-16 -z-10 h-[44svh] lg:inset-y-0 lg:left-[28%] lg:top-0 lg:h-auto">
        <LazyHeroScene />
      </div>
      <div
        aria-hidden
        className="absolute inset-0 -z-10 hidden lg:block lg:bg-gradient-to-r lg:from-night lg:via-night/50 lg:to-transparent"
      />

      <div className="mx-auto w-full max-w-6xl px-6">
        <RevealBlock immediate delayMs={1700}>
          <span className="glass inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs text-foreground/80">
            <span className="size-1.5 animate-pulse rounded-full bg-moss" />
            Voice-first AI coaching for CS students
          </span>
        </RevealBlock>
        <h1 className="mt-6 max-w-5xl text-[clamp(2.75rem,6.6vw,5.75rem)] font-light leading-[1.02] tracking-tight">
          <RevealText immediate as="span" text="Stop cramming." className="block" delayMs={1800} />
          <RevealText
            immediate
            as="span"
            text="Grow skills that stay."
            className="block text-moss"
            delayMs={2050}
          />
        </h1>
        <RevealBlock
          immediate
          delayMs={2400}
          className="mt-8 max-w-xl text-lg leading-relaxed text-foreground/70"
        >
          <p>
            Talk concepts through with AI mentors who teach, interview and hold you accountable.
            Your 3D garden grows only from what you actually demonstrate, and every leaf cites its
            evidence.
          </p>
        </RevealBlock>
        <RevealBlock immediate delayMs={2600} className="mt-10 flex flex-wrap gap-3">
          <Link
            href={{ pathname: "/sign-up" }}
            className="group inline-flex items-center gap-2 rounded-xl bg-moss px-6 py-3.5 font-medium text-night transition hover:brightness-110"
          >
            Start growing <Arrow />
          </Link>
          <SectionLink
            id="mentors"
            className="glass inline-flex items-center gap-2 rounded-xl px-6 py-3.5 font-medium transition hover:border-white/20"
          >
            Meet the mentors
          </SectionLink>
          <SectionLink
            id="how"
            className="group inline-flex items-center gap-2 rounded-xl border border-white/15 px-6 py-3.5 font-medium text-foreground/80 transition hover:border-white/30 hover:text-foreground"
          >
            How it works <Arrow />
          </SectionLink>
        </RevealBlock>
        <RevealBlock immediate delayMs={2800} className="mt-14 flex flex-wrap gap-x-12 gap-y-6">
          <Stat value={<CountUp to={6} />} label="AI mentors, one garden" />
          <Stat value={<CountUp to={4} />} label="Skill dimensions per concept" />
          <Stat value={<CountUp to={100} suffix="%" />} label="Of growth backed by evidence" />
        </RevealBlock>
      </div>
    </section>
  );
}

function Stat({ value, label }: { value: ReactNode; label: string }) {
  return (
    <div>
      <p className="text-4xl font-light tabular-nums">{value}</p>
      <p className="mt-1 text-sm text-foreground/55">{label}</p>
    </div>
  );
}

function Mentors() {
  return (
    <section id="mentors" className="scroll-mt-28 border-t border-white/5 py-24">
      <div className="mx-auto max-w-3xl px-6 text-center">
        <Eyebrow className="justify-center">The mentors</Eyebrow>
        <RevealText
          text="Six voices. One garden."
          className="mt-4 text-[clamp(2.25rem,5vw,4rem)] font-light leading-tight tracking-tight"
        />
        <RevealBlock className="mt-4 text-foreground/60">
          <p>
            Each mentor has one job, its own designed voice, and a plan for every phase of the
            session. All of them write to the same evidence-backed memory.
          </p>
        </RevealBlock>
      </div>

      <div className="mt-14 flex flex-col gap-4">
        <Marquee duration="55s">
          {MENTORS.map((m) => (
            <div
              key={m.id}
              className="glass flex w-80 shrink-0 items-center gap-4 rounded-2xl px-5 py-4"
            >
              <span
                className="grid size-11 shrink-0 place-items-center rounded-full text-sm font-semibold text-night"
                style={{ background: m.color }}
              >
                {m.id[0]!.toUpperCase()}
              </span>
              <div className="min-w-0">
                <p className="font-medium capitalize">
                  {m.id} <span className="font-normal text-foreground/50">· {m.role}</span>
                </p>
                <p className="truncate text-sm text-foreground/60">{m.line}</p>
              </div>
            </div>
          ))}
        </Marquee>
        <Marquee duration="70s" reverse>
          {CONCEPTS.map((c) => (
            <span
              key={c}
              className="shrink-0 rounded-full border border-white/10 bg-dusk/40 px-5 py-2.5 text-sm text-foreground/70"
            >
              {c}
            </span>
          ))}
        </Marquee>
      </div>
    </section>
  );
}

function Marquee({
  children,
  duration,
  reverse,
}: {
  children: ReactNode;
  duration: string;
  reverse?: boolean;
}) {
  return (
    <div className="marquee overflow-hidden">
      <div
        className="marquee-track flex w-max"
        data-reverse={reverse || undefined}
        style={{ "--duration": duration } as CSSProperties}
      >
        {[0, 1].map((copy) => (
          <div
            key={copy}
            aria-hidden={copy === 1 || undefined}
            className="flex shrink-0 gap-4 pr-4"
          >
            {children}
          </div>
        ))}
      </div>
    </div>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="mx-auto w-full max-w-6xl scroll-mt-28 px-6 py-24">
      <Eyebrow>How it works</Eyebrow>
      <RevealText
        text="From conversation to evidence."
        className="mt-4 max-w-3xl text-[clamp(2.25rem,5vw,4rem)] font-light leading-tight tracking-tight"
      />
      <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((step, i) => (
          <RevealBlock key={step.title} delayMs={i * 120}>
            <article className="h-full rounded-2xl border border-white/10 bg-dusk/50 p-4 transition hover:border-white/20 hover:bg-dusk/70">
              {step.art}
              <p className="mt-5 px-1 text-xs tabular-nums text-foreground/40">0{i + 1}</p>
              <h3 className="mt-1 px-1 text-2xl font-light">{step.title}</h3>
              <p className="mt-2 px-1 pb-2 text-sm leading-relaxed text-foreground/60">
                {step.body}
              </p>
            </article>
          </RevealBlock>
        ))}
      </div>
    </section>
  );
}

function GardenDashboard() {
  return (
    <section id="garden" className="scroll-mt-28 border-y border-white/5 bg-dusk/20 py-24">
      <div className="mx-auto grid w-full max-w-6xl gap-14 px-6 lg:grid-cols-[1fr_1.15fr] lg:items-center">
        <div>
          <Eyebrow>The garden</Eyebrow>
          <RevealText
            text="Your garden is your dashboard."
            className="mt-4 text-[clamp(2.25rem,5vw,4rem)] font-light leading-tight tracking-tight"
          />
          <RevealBlock className="mt-5 max-w-md text-foreground/60">
            <p>
              Every concept is a plant, and every plant part is a skill dimension. Zoom into any of
              them to see the scores, the trend and the moments that earned it.
            </p>
          </RevealBlock>
          <RevealBlock className="mt-8 flex flex-wrap items-center gap-2 text-xs">
            {PLANT_STAGES.map((stage, i) => (
              <span key={stage} className="flex items-center gap-2">
                <span
                  className="rounded-full border border-white/10 px-3 py-1 capitalize"
                  style={{ opacity: 0.45 + i * 0.11 }}
                >
                  {stage}
                </span>
                {i < PLANT_STAGES.length - 1 && <span className="text-foreground/30">→</span>}
              </span>
            ))}
          </RevealBlock>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(DIMENSION_TO_PART).map(([dimension, part], i) => (
            <RevealBlock key={dimension} delayMs={i * 120}>
              <article className="h-full rounded-2xl border border-white/10 bg-night/60 p-6">
                <p className="text-xs uppercase tracking-[0.25em] text-glow">grows {part}</p>
                <h3 className="mt-3 text-2xl font-light capitalize">{dimension}</h3>
                <p className="mt-2 text-sm leading-relaxed text-foreground/60">
                  {DIMENSION_COPY[dimension as keyof typeof DIMENSION_TO_PART]}
                </p>
              </article>
            </RevealBlock>
          ))}
        </div>
      </div>
    </section>
  );
}

function Principles() {
  return (
    <section id="principles" className="mx-auto w-full max-w-6xl scroll-mt-28 px-6 py-24">
      <Eyebrow>Actually intelligent</Eyebrow>
      <RevealText
        text="Growth you can audit."
        className="mt-4 max-w-3xl text-[clamp(2.25rem,5vw,4rem)] font-light leading-tight tracking-tight"
      />
      <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PRINCIPLES.map((p, i) => (
          <RevealBlock key={p.title} delayMs={i * 120}>
            <article className="h-full rounded-2xl border border-white/10 bg-dusk/50 p-6">
              <SproutMark className="size-7 text-foreground/70" />
              <h3 className="mt-6 text-xl font-light">{p.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-foreground/60">{p.body}</p>
            </article>
          </RevealBlock>
        ))}
      </div>
    </section>
  );
}

function Practice() {
  return (
    <section className="border-t border-white/5 py-24">
      <div className="mx-auto w-full max-w-6xl px-6">
        <Eyebrow>Practice</Eyebrow>
        <RevealText
          text="What are you preparing for?"
          className="mt-4 max-w-2xl text-[clamp(2.25rem,5vw,4rem)] font-light leading-tight tracking-tight"
        />
        <RevealBlock className="mt-10 flex flex-wrap gap-3">
          {PRACTICE.map((item) => (
            <span
              key={item}
              className="rounded-xl border border-white/10 px-4 py-2.5 text-sm text-foreground/75 transition hover:border-moss/60 hover:text-foreground"
            >
              {item}
            </span>
          ))}
        </RevealBlock>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="relative isolate overflow-hidden py-32 text-center">
      <div
        aria-hidden
        className="absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(50% 60% at 50% 100%, rgb(63 174 122 / 0.25), transparent 70%)",
        }}
      />
      <div className="mx-auto max-w-3xl px-6">
        <RevealText
          text="Plant your first concept tonight."
          className="text-[clamp(2.5rem,6vw,5rem)] font-light leading-tight tracking-tight"
        />
        <RevealBlock className="mt-10 flex flex-wrap justify-center gap-3">
          <Link
            href={{ pathname: "/sign-up" }}
            className="group inline-flex items-center gap-2 rounded-xl bg-moss px-7 py-4 font-medium text-night transition hover:brightness-110"
          >
            Start growing <Arrow />
          </Link>
          <Link
            href={{ pathname: "/sign-in" }}
            className="glass inline-flex items-center rounded-xl px-7 py-4 font-medium transition hover:border-white/20"
          >
            I already have a garden
          </Link>
        </RevealBlock>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-white/5">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 text-sm text-foreground/50">
        <span className="flex items-center gap-2">
          <SproutMark className="size-5" /> Skill Garden
        </span>
        <span>Every leaf is earned.</span>
      </div>
    </footer>
  );
}

function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <svg viewBox="0 0 20 20" className="dot-pulse size-5 text-moss" aria-hidden>
        {[
          [10, 3],
          [16, 7],
          [14, 15],
          [6, 15],
          [4, 7],
        ].map(([cx, cy], i) => (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r="1.8"
            fill="currentColor"
            style={{ "--i": i } as CSSProperties}
          />
        ))}
      </svg>
      <span className="rounded-full border border-white/10 bg-dusk/50 px-3 py-1 text-xs tracking-wide text-foreground/60">
        {children}
      </span>
    </div>
  );
}

function Arrow() {
  return (
    <svg
      viewBox="0 0 16 16"
      className="size-4 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden
    >
      <path d="M5 11 11 5M6 5h5v5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
