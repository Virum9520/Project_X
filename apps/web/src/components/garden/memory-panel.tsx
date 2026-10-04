"use client";

import type { Character, GardenDataset, MemoryItem } from "@sg/contracts";
import { useState, useTransition } from "react";

import { correctMemory, deleteMemory } from "@/app/(app)/garden/actions";

import { Panel, cap, formatDay } from "./primitives";

const STATUS_STYLE: Record<MemoryItem["status"], string> = {
  accepted: "bg-moss/20 text-moss",
  provisional: "bg-glow/15 text-glow",
  disputed: "bg-ember/20 text-ember",
};

/**
 * What each character remembers about the learner, and why. Learners can correct an item, or
 * delete private ones, and see exactly which plants the change touches before they commit.
 *
 * With live data a correction is saved through the API as a new memory revision (the old wording
 * stays in history) and a delete removes one of your private reflections. With sample data, edits
 * are local only.
 */
export function MemoryPanel({
  dataset,
  cutoff,
  live,
  onFocusPlant,
}: {
  dataset: GardenDataset;
  cutoff: number;
  /** True when the dataset is the learner's real data, so edits are saved to the API. */
  live: boolean;
  onFocusPlant: (key: string) => void;
}) {
  // Keyed by the id the dataset loaded with. A saved correction swaps in its new revision.
  const [revised, setRevised] = useState<Record<string, MemoryItem>>({});
  const [localText, setLocalText] = useState<Record<string, string>>({});
  const [deleted, setDeleted] = useState<ReadonlySet<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const titleOf = new Map(dataset.plants.map((p) => [p.key, p.title]));

  const items = dataset.memories
    .filter((m) => Date.parse(m.createdAt) <= cutoff && !deleted.has(m.id))
    .map((m) => ({ slot: m.id, item: revised[m.id] ?? m }));
  const characters = [...new Set(items.map((x) => x.item.character))] as Character[];

  const save = (slot: string, m: MemoryItem, content: string) => {
    const text = content.trim() || m.text;
    if (!live) {
      setLocalText((s) => ({ ...s, [slot]: text }));
      setEditing(null);
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await correctMemory(m.id, text);
      if (result.ok) {
        setRevised((s) => ({ ...s, [slot]: result.data }));
        setEditing(null);
      } else setError(result.message);
    });
  };

  const remove = (slot: string, m: MemoryItem) => {
    if (!live) {
      setDeleted((s) => new Set(s).add(slot));
      return;
    }
    setError(null);
    startTransition(async () => {
      const result = await deleteMemory(m.id);
      if (result.ok) setDeleted((s) => new Set(s).add(slot));
      else setError(result.message);
    });
  };

  return (
    <Panel id="memory" title="Memory">
      <p className="-mt-1 mb-3 text-xs text-foreground/50">
        What your mentors remember, and why. Corrections are saved as new revisions; nothing is
        rewritten silently.
        {live ? "" : " (Sample data: edits are not saved.)"}
      </p>
      {error && (
        <p role="alert" className="mb-3 rounded-lg bg-ember/15 px-3 py-2 text-xs text-ember">
          {error}
        </p>
      )}
      {items.length === 0 && (
        <p className="text-sm text-foreground/60">
          Nothing is remembered yet. Your mentors will add notes as you practise.
        </p>
      )}
      <div className="space-y-4">
        {characters.map((c) => (
          <div key={c}>
            <h3 className="mb-1.5 text-sm font-medium">{cap(c)}</h3>
            <ul className="space-y-2">
              {items
                .filter((x) => x.item.character === c)
                .map(({ slot, item: m }) => {
                  const text = localText[slot] ?? m.text;
                  const isEditing = editing === slot;
                  return (
                    <li
                      key={slot}
                      className="rounded-xl border border-white/10 bg-night/30 p-3 text-sm"
                    >
                      {isEditing ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            save(slot, m, draft);
                          }}
                        >
                          <label
                            className="block text-xs text-foreground/60"
                            htmlFor={`mem-${slot}`}
                          >
                            Correct this memory
                          </label>
                          <textarea
                            id={`mem-${slot}`}
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            rows={2}
                            maxLength={2000}
                            className="mt-1 w-full rounded-lg border border-white/15 bg-night/70 p-2 text-sm outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40"
                          />
                          <p className="mt-1 text-xs text-ember">
                            {m.affects.length
                              ? `This will change: ${m.affects.map((k) => titleOf.get(k) ?? k).join(", ")}.`
                              : "This affects no plants or stats."}
                          </p>
                          <div className="mt-2 flex gap-2">
                            <button
                              type="submit"
                              disabled={pending}
                              className="rounded-lg bg-moss px-3 py-1 text-xs font-medium text-night outline-none focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-60"
                            >
                              {pending ? "Saving…" : "Save correction"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditing(null)}
                              className="rounded-lg px-3 py-1 text-xs text-foreground/70 outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
                            >
                              Cancel
                            </button>
                          </div>
                        </form>
                      ) : (
                        <>
                          <p>{text}</p>
                          <p className="mt-1 text-xs text-foreground/60">
                            <span className="text-foreground/40">Why: </span>
                            {m.why}
                          </p>
                          <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.7rem] text-foreground/50">
                            <span className={`rounded-full px-2 py-0.5 ${STATUS_STYLE[m.status]}`}>
                              {m.status}
                            </span>
                            <span>{m.layer}</span>
                            <span>{Math.round(m.confidence * 100)}% confident</span>
                            <span>{formatDay(m.createdAt)}</span>
                            {m.layer === "private" && (
                              <span className="text-glow">only you can see this</span>
                            )}
                          </p>
                          {m.affects.length > 0 && (
                            <p className="mt-1.5 flex flex-wrap gap-1.5 text-[0.7rem]">
                              <span className="text-foreground/40">Shapes:</span>
                              {m.affects.map((k) => (
                                <button
                                  key={k}
                                  type="button"
                                  onClick={() => onFocusPlant(k)}
                                  className="rounded-full bg-white/5 px-2 py-0.5 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow/60"
                                >
                                  {titleOf.get(k) ?? k}
                                </button>
                              ))}
                            </p>
                          )}
                          <div className="mt-2 flex gap-1 text-xs">
                            <button
                              type="button"
                              onClick={() => {
                                setDraft(text);
                                setEditing(slot);
                              }}
                              className="rounded-md px-2 py-1 text-glow outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
                            >
                              Correct
                            </button>
                            {m.deletable && (
                              <button
                                type="button"
                                disabled={pending}
                                onClick={() => remove(slot, m)}
                                className="rounded-md px-2 py-1 text-ember outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60 disabled:opacity-60"
                              >
                                Delete
                              </button>
                            )}
                          </div>
                        </>
                      )}
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </div>
    </Panel>
  );
}
