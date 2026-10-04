# Skill Garden: 3-minute demo script

Track: "AI, Actually Intelligent". The point to land: **the garden grows only from evidence the
learner demonstrated, and you can audit every leaf.**

## Before you go on stage

The owner runs these once against a **local or dev** database (the seed refuses production).
The build sessions have not run them.

```bash
# 1. Sign up (or sign in) as the demo learner in the web app and copy your Clerk user id (user_...).
# 2. Add that email to DEMO_ACCOUNT_EMAILS in the root .env (compressed review clock for live demos).
# 3. Preview the scripted history (touches no database):
uv run python -m sg_core.demo describe
# 4. Seed (needs a migrated DB; the shared dev DB needs --allow-dev):
uv run python -m sg_core.demo seed --clerk-user-id user_XXXX --email you@example.com --allow-dev
```

The seed is idempotent (re-running changes nothing). It replays 14 written transcripts through the
real post-call pipeline with a clock matching each conversation, so every revision, plant state and
citation is what production would have written. Only the judge is scripted; each quoted line is
still validated as a verbatim learner turn.

What the garden shows after seeding (fictional learner "Maya Rao", about 3.5 weeks of history):

| Concept | Earned stage | Why it is interesting |
|---|---|---|
| dsa.big_o | retained | explanation, application, transfer, then a spaced recall review; now due again |
| dsa.binary_search | transfer | clean climb |
| dsa.hash_tables | independent | started with a misconception, fixed on the second try |
| databases.indexes | independent | |
| dsa.bfs | sprouting | application solved only with hints: assisted ghost track, independent score 0 |
| dsa.dfs | assisted | hint-only evidence never counts as independent |
| os.race_conditions, databases.transactions_acid | sprouting | the second came from a Teach-back |
| dsa.heaps, dsa.union_find | no plant | an ambiguous answer, and an answer that tried to talk the grader into a pass |

Because the evidence is weeks old, several plants are due or wilting, which fills the reviews panel.

Pre-flight (5 minutes before): signed in as the demo learner, `/garden` shows plants, mic permission
granted, `ELEVENLABS_API_KEY`, `OPENROUTER_API_KEY` and the webhook secret set, the post-call
webhook reachable, browser zoom 100%, a second tab on `/session?concept=dsa.binary_search`.
Fallback if voice fails: narrate over `/garden` and the seeded history (beats 1 to 3 and 6 are real data).

## Beats

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:20 | Landing page, hero scene | "Students cram, pass, and forget. Skill Garden is voice coaching where a 3D garden is your analytics dashboard, and it only grows from things you actually showed." |
| 0:20 to 0:50 | `/garden`: orbit, click big_o | "Each plant is a concept, each part a skill: explanation, application, transfer, retention. Click a plant and you see the exact quotes that grew it." Open a leaf and show the cited learner quote. |
| 0:50 to 1:15 | Click bfs, then dfs | "Maya solved BFS with hints. The garden shows that as assisted, a ghost track, and the independent score is zero. Assisted is never counted as independent." |
| 1:15 to 2:15 | `/session?concept=dsa.binary_search`, live voice | Answer Drona's question out loud (or do a Teach-back). Point at the evidence ticker: a provisional glow appears within seconds. "That glow is provisional. The full judge confirms or retracts it after the call." End the call. |
| 2:15 to 2:40 | Garden updates | The glow is confirmed and the plant grows. "A model proposed evidence. A deterministic, versioned rules engine decided the growth. Same evidence, same plant, replayable." |
| 2:40 to 3:00 | Heaps and union-find (no plant), then close | "Ambiguous answers grow nothing and queue a re-check. An answer that begged the grader for a pass grew nothing. Uploaded documents are data, never instructions." Close: "Every leaf is earned." |

## If asked

- **Is the history real?** No. It is a written script replayed through the real pipeline. Say so.
- **Can the LLM inflate a score?** No. It emits verdicts; every citation must be a verbatim learner
  quote; assistance can only be raised by agent notes; growth is written only by `sg_core.rules`.
- **Why does time matter?** Spaced repetition: plants go DUE, then WILTING. The demo profile
  compresses the clock to minutes so wilting and retention can be shown live.
- **Phone calls?** Web calls only; the phone channel is an interface stub.

## Not verified live

The voice session, post-call webhook and judge quality need real provider keys and have not been
exercised by the build sessions. Run beat 4 end to end once before presenting.
