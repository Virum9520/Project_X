import type { Character } from "@sg/contracts";
import type { Route } from "next";

export interface Coach {
  id: Character;
  name: string;
  role: string;
  /** What they do, in one plain sentence. */
  blurb: string;
  /** Where the learner starts a session with them. */
  href: Route;
  cta: string;
  /** Short title used on cards that launch the coach. */
  feature: string;
  hint: string;
}

export const COACHES: Coach[] = [
  {
    id: "drona",
    name: "Drona",
    role: "Teacher",
    blurb: "Teaches a concept, quizzes you out loud, then has you teach it back.",
    href: "/session",
    cta: "Start a voice session",
    feature: "Voice session",
    hint: "Concept by concept, out loud",
  },
  {
    id: "vidura",
    name: "Vidura",
    role: "HR interviewer",
    blurb: "Runs behavioural rounds, alone or as part of a two-person panel.",
    href: "/interview",
    cta: "Start an HR or panel interview",
    feature: "HR and panel interview",
    hint: "Behavioural questions",
  },
  {
    id: "arjuna",
    name: "Arjuna",
    role: "Technical interviewer",
    blurb: "Live coding interviews where you think aloud and your tests really run.",
    href: "/interview/technical",
    cta: "Start a technical interview",
    feature: "Technical interview",
    hint: "Think aloud, with code",
  },
  {
    id: "bhima",
    name: "Bhima",
    role: "Accountability",
    blurb: "Calls to check on your commitments and quiz what you still remember.",
    href: "/settings/schedule",
    cta: "Set your call schedule",
    feature: "Accountability calls",
    hint: "Commitments and check-ins",
  },
  {
    id: "krishna",
    name: "Krishna",
    role: "Future self",
    blurb: "A daily message in your own voice from the person you are becoming.",
    href: "/future-self",
    cta: "Open future-self messages",
    feature: "Future-self message",
    hint: "Hear from the you to come",
  },
  {
    id: "sanjaya",
    name: "Sanjaya",
    role: "Recap narrator",
    blurb: "Narrates a flythrough of your garden and what grew this week.",
    href: "/recap",
    cta: "Watch your recap",
    feature: "Weekly recap",
    hint: "A narrated garden flythrough",
  },
];

export const COACH_BY_ID = Object.fromEntries(COACHES.map((c) => [c.id, c])) as Record<
  Character,
  Coach
>;
