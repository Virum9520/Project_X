"use client";

import { AvatarStage, mockAlignment, useLipSync } from "@sg/three/avatar";
import { useState } from "react";

const SAMPLE = "Welcome back. Today we will practise explaining how a hash map handles collisions.";

export function AvatarDemo() {
  const driver = useLipSync();
  const [text, setText] = useState(SAMPLE);
  const [msPerChar, setMsPerChar] = useState(65);
  const [level, setLevel] = useState(0);
  const [vrmInput, setVrmInput] = useState("");
  const [vrmUrl, setVrmUrl] = useState<string | undefined>();

  function speak() {
    driver.reset();
    driver.start();
    driver.pushAlignment(mockAlignment(text, msPerChar));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="h-96 overflow-hidden rounded-xl border border-black/10 bg-gradient-to-b from-sky-100 to-emerald-100">
        <AvatarStage driver={driver} vrmUrl={vrmUrl} className="h-full w-full" />
      </div>

      <label className="flex flex-col gap-1 text-sm">
        Text (mock alignment)
        <textarea
          className="rounded border border-black/20 p-2"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <button
          type="button"
          onClick={speak}
          className="rounded bg-emerald-700 px-4 py-2 font-medium text-white"
        >
          Speak
        </button>
        <button
          type="button"
          onClick={() => driver.reset()}
          className="rounded border border-black/20 px-4 py-2"
        >
          Stop
        </button>
        <label className="flex items-center gap-2">
          ms/char {msPerChar}
          <input
            type="range"
            min={30}
            max={140}
            value={msPerChar}
            onChange={(e) => setMsPerChar(Number(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-2">
          Level fallback {level.toFixed(2)}
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={level}
            onChange={(e) => {
              const v = Number(e.target.value);
              setLevel(v);
              driver.setLevel(v);
            }}
          />
        </label>
      </div>
      <form
        className="flex items-center gap-2 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          // Same-origin paths only (e.g. /avatars/drona.vrm). Empty = procedural placeholder.
          setVrmUrl(vrmInput.startsWith("/") && !vrmInput.startsWith("//") ? vrmInput : undefined);
        }}
      >
        <input
          className="flex-1 rounded border border-black/20 p-2"
          placeholder="/avatars/model.vrm (optional, from public/)"
          value={vrmInput}
          onChange={(e) => setVrmInput(e.target.value)}
        />
        <button type="submit" className="rounded border border-black/20 px-4 py-2">
          Load VRM
        </button>
      </form>
    </div>
  );
}
