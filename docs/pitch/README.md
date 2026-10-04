# Skill Garden: pitch pack

Hackathon track: **AI, Actually Intelligent.** Pair with the [demo script](../demo-script.md).

## One line

Voice-first AI coaching for CS students where a 3D garden is your dashboard and grows only from
what you demonstrated; every leaf cites its evidence.

## Problem

Interview and exam prep rewards cramming. Students cannot tell what they actually know, tutors
over-credit hint-assisted answers, and nothing keeps a skill from fading after the exam.

## Solution

Six voice mentors (Drona teaches, Arjuna runs technical interviews with live code, Vidura does HR
and panel rounds, Bhima holds you accountable, Krishna guides, Sanjaya narrates) all write to one
evidence-backed memory. The **Garden Dashboard** renders it: each concept is a plant, each part a
skill dimension (explanation, application, transfer, retention).

## Why it is "actually intelligent"

1. **Evidence, not vibes.** An LLM judge proposes verdicts; each must cite a verbatim learner quote or it is rejected.
2. **Deterministic growth.** Only the versioned rules engine (`sg_core.rules`) changes the garden, so growth is replayable and auditable.
3. **Assisted is not independent.** Hint-assisted answers form a separate ghost track.
4. **Adversarial-safe.** Documents and transcripts are data, never instructions; an answer that begs for a pass grows nothing (it is in the demo data).
5. **Memory that persists.** The Memory Persistence Engine keeps provisional versus confirmed memory, retracts mistakes, and schedules spaced reviews so plants wilt when skills fade.

## Audience

US CS students and job seekers (internship and new-grad recruiting). No market-size figures are
claimed here; add sourced numbers before using any.

## Versus a chat tutor

Voice-first with distinct mentor voices; a visible, auditable record instead of a chat log;
integrity guarantees (citations, assisted separation, deterministic rules) a generic tutor lacks.

## Slide outline (6 slides)

1. Cram, pass, forget (problem; one stat only if sourced)
2. The garden: screenshot of `/garden` with a cited leaf open
3. How a leaf is earned: voice, judge, validator, rules engine (pipeline diagram)
4. Integrity: assisted ghost track, rejected citations, the union-find "gaming" case
5. Live demo (3 minutes, see the script)
6. Roadmap: phone channel, AWS production (C24), judge calibration on real calls

## Likely judge questions

- **How do you stop hallucinated evidence?** Verbatim-quote validation against the learner's turns, and a deterministic rules engine that never trusts a model for scores.
- **How do you know the judge is good?** Not yet calibrated on real calls; that is the next step. Verdicts are stored as assessment revisions and judge calls are ledgered, so they can be reviewed.
- **Cost and latency?** Provider calls are ledgered with budget holds. The live glow comes from a fast micro-judge and is confirmed after the call.
- **Privacy?** Every query is scoped to the user; CSRF and audit middleware; the owner console is limited to an allowlist with MFA.

## Honest status

The demo history is scripted (say so). Voice, webhooks and judge quality have not been run against
live providers by the build sessions; verify before presenting.
