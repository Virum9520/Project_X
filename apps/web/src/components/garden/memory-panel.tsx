"use client";

import type { Character, GardenDataset, MemoryItem } from "@sg/contracts";
import { useState } from "react";

import { Panel, cap, formatDay } from "./primitives";

const STATUS_STYLE: Record<MemoryItem["status"], string> = {
  accepted: "bg-moss/20 text-moss",
  provisional: "bg-glow/15 text-glow",
  disputed: "bg-ember/20 text-ember",
};

/**
 * What each character remembers about the learner, and why. Learners can correct an item, or
 * delete private ones, and see exactly which plants the change touches before they commit.
 * Edits here are local sample-data state until the Memory Persistence Engine API (C09) exists.
 */
export function MemoryPanel({
  dataset,
  cutoff,
  onFocusPlant,
}: {
  dataset: GardenDataset;
  cutoff: number;
  onFocusPlant: (key: string) => void;
}) {
  const [edits, setEdits] = useState<Record<string, { text?: string; deleted?: boolean }>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const titleOf = new Map(dataset.plants.map((p) => [p.key, p.title]));

  const items = dataset.memories.filter(
    (m) => Date.parse(m.createdAt) <= cutoff && !edits[m.id]?.deleted,
  );
  const characters = [...new Set(items.map((m) => m.character))] as Character[];

  return (
    <Panel id="memory" title="Memory">
      <p className="-mt-1 mb-3 text-xs text-foreground/50">
        What your mentors remember, and why. Corrections are saved as new revisions; nothing is
        rewritten silently. (Sample data: edits are not persisted yet.)
      </p>
      <div className="space-y-4">
        {characters.map((c) => (
          <div key={c}>
            <h3 className="mb-1.5 text-sm font-medium">{cap(c)}</h3>
            <ul className="space-y-2">
              {items
                .filter((m) => m.character === c)
                .map((m) => {
                  const text = edits[m.id]?.text ?? m.text;
                  const isEditing = editing === m.id;
                  return (
                    <li
                      key={m.id}
                      className="rounded-xl border border-white/10 bg-night/30 p-3 text-sm"
                    >
                      {isEditing ? (
                        <form
                          onSubmit={(e) => {
                            e.preventDefault();
                            setEdits((s) => ({
                              ...s,
                              [m.id]: { ...s[m.id], text: draft.trim() || m.text },
                            }));
                            setEditing(null);
                          }}
                        >
                          <label
                            className="block text-xs text-foreground/60"
                            htmlFor={`mem-${m.id}`}
                          >
                            Correct this memory
                          </label>
                          <textarea
                            id={`mem-${m.id}`}
                            value={draft}
                            onChange={(e) => setDraft(e.target.value)}
                            rows={2}
                            className="mt-1 w-full rounded-lg border border-white/15 bg-night/70 p-2 text-sm outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40"
                          />
                          <p className="mt-1 text-xs text-ember">
                            {m.affects.length
                              ? `This will change: ${m.affects.map((k) => titleOf.get(k)).join(", ")}.`
                              : "This affects no plants or stats."}
                          </p>
                          <div className="mt-2 flex gap-2">
                            <button
                              type="submit"
                              className="rounded-lg bg-moss px-3 py-1 text-xs font-medium text-night outline-none focus-visible:ring-2 focus-visible:ring-glow"
                            >
                              Save correction
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
                                  {titleOf.get(k)}
                                </button>
                              ))}
                            </p>
                          )}
                          <div className="mt-2 flex gap-1 text-xs">
                            <button
                              type="button"
                              onClick={() => {
                                setDraft(text);
                                setEditing(m.id);
                              }}
                              className="rounded-md px-2 py-1 text-glow outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
                            >
                              Correct
                            </button>
                            {m.deletable && (
                              <button
                                type="button"
                                onClick={() =>
                                  setEdits((s) => ({ ...s, [m.id]: { ...s[m.id], deleted: true } }))
                                }
                                className="rounded-md px-2 py-1 text-ember outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
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
