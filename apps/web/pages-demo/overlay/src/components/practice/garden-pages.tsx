"use client";

import { useCallback, useRef, useState } from "react";

import { buildRecap } from "@/app/(app)/recap/actions";
import { GardenLab } from "@/app/lab/garden/garden-lab";
import { HomeView } from "@/components/app-pages/home-view";
import { SessionsView } from "@/components/app-pages/sessions-view";
import { GardenDashboard } from "@/components/garden/dashboard";
import { RecapPlayer } from "@/components/recap/recap-player";
import { parseState } from "@/lib/garden/state";
import { usePracticeDataset } from "@/lib/practice/dataset";
import { useCoachVoice } from "@/lib/practice/speech";

import { VoiceToggle } from "./conversation";

/**
 * The learner pages of the static site. They render in the browser only: the garden is the
 * sample learner's history re-dated to today plus whatever was practised in this browser.
 */

const LEARNER_NAME = "Virum";

const urlParams = () => Object.fromEntries(new URLSearchParams(window.location.search));

export function GardenPage() {
  const dataset = usePracticeDataset();
  // Deep links (`?focus=plant:dsa.bfs`, filters, time travel) work like in the full app.
  const [initial] = useState(() => parseState(urlParams(), dataset));
  return <GardenDashboard dataset={dataset} initialState={initial} isMock={false} />;
}

export function HomePage() {
  const dataset = usePracticeDataset();
  return <HomeView name={LEARNER_NAME} dataset={dataset} isMock={false} />;
}

export function SessionsPage() {
  const dataset = usePracticeDataset();
  return <SessionsView dataset={dataset} isMock={false} />;
}

export function RecapPage() {
  const dataset = usePracticeDataset();
  const [initial] = useState(() => buildRecap(dataset));
  const { say, silence } = useCoachVoice("sanjaya");
  const queue = useRef<string[]>([]);
  const running = useRef(false);

  // Segments queue up so a slow voice finishes one before reading the next.
  const narrate = useCallback(
    (text: string | null) => {
      if (text === null) {
        queue.current = [];
        silence();
        return;
      }
      queue.current.push(text);
      if (running.current) return;
      running.current = true;
      void (async () => {
        while (queue.current.length) await say(queue.current.shift()!);
        running.current = false;
      })();
    },
    [say, silence],
  );

  return (
    <RecapPlayer
      dataset={dataset}
      initial={initial}
      canShare={false}
      onNarrate={narrate}
      extra={<VoiceToggle />}
    />
  );
}

export function LabPage() {
  const [focus] = useState(() => new URLSearchParams(window.location.search).get("focus"));
  return <GardenLab initialFocus={focus} />;
}
