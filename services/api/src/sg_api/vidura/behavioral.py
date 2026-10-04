"""Behavioural question bank for Vidura and the Panel.

Each behavioural concept (`behavioral.*` in `cs-core@v1`) has a few STAR-shaped prompts. Hints are
follow-up probes for the interviewer, keyed to the communication behaviours (structure,
specificity, ownership, conciseness), never judgements about the person. Everything is pure and
deterministic; `sg_api.drona.questions` delegates here for `kind=behavioral`.
"""

from collections.abc import Iterable

# Competencies Vidura rotates through when the session has no focus concept, in order.
# `behavioral.star_method` is a skill to be shown through the other answers, not a topic.
ROTATION: tuple[str, ...] = (
    "behavioral.teamwork",
    "behavioral.conflict_resolution",
    "behavioral.ownership",
    "behavioral.failure_learning",
    "behavioral.technical_project_deep_dive",
    "behavioral.feedback",
    "behavioral.ambiguity",
    "behavioral.leadership_influence",
    "behavioral.motivation_fit",
)

# Follow-ups that ask for the missing part of a story, one per communication behaviour.
PROBES: dict[str, str] = {
    "structure": "What happened first, and how did it end?",
    "specificity": "Can you give a concrete example, with a number or a tool you used?",
    "ownership": "What did you personally do, as opposed to the team?",
    "conciseness": "In a sentence or two, what was the main point?",
    "result": "What was the outcome, and how did you know?",
    "reflection": "Looking back, what would you do differently?",
}

BANK: dict[str, tuple[str, ...]] = {
    "behavioral.teamwork": (
        "Tell me about a time you worked in a team toward a shared goal. What was your part?",
        "Describe a project where you depended on teammates to finish. How did you keep it moving?",
    ),
    "behavioral.conflict_resolution": (
        "Tell me about a time you disagreed with a teammate. How did you handle it?",
        "Describe a technical disagreement you had to settle. What happened in the end?",
    ),
    "behavioral.ownership": (
        "Tell me about a time you took responsibility for something nobody assigned to you.",
        "Describe something you owned end to end. What decisions were yours?",
    ),
    "behavioral.failure_learning": (
        "Tell me about a time something you built or planned did not work. What did you do next?",
        "Describe a mistake you made on a project and what you changed afterwards.",
    ),
    "behavioral.technical_project_deep_dive": (
        "Walk me through a technical project you are proud of. What was your role?",
        "Pick one design decision from a project you built. What else did you consider, and why "
        "did you choose that?",
    ),
    "behavioral.feedback": (
        "Tell me about feedback that was hard to hear. What did you do with it?",
        "Describe a time you gave a peer feedback. How did you approach it?",
    ),
    "behavioral.ambiguity": (
        "Tell me about a time the requirements were unclear. How did you decide what to build?",
        "Describe a problem you had little guidance on. How did you get started?",
    ),
    "behavioral.leadership_influence": (
        "Tell me about a time you led a group or influenced a decision without being in charge.",
        "Describe a time you convinced others to try your approach. What did you say or show?",
    ),
    "behavioral.motivation_fit": (
        "Why are you interested in this kind of role, and what have you done that shows it?",
        "Tell me about a project that made you want to work in this field.",
    ),
    "behavioral.star_method": (
        "Tell me about a time you learned something quickly to finish a task.",
        "Describe a deadline you had to meet. What did you do and what came of it?",
    ),
}

GENERIC = "Tell me about a time that shows {topic}. What did you do and what happened?"


def prompts_for(concept_key: str, title: str) -> list[str]:
    bank = BANK.get(concept_key)
    return list(bank) if bank else [GENERIC.format(topic=title.lower())]


def probe_hints(extra: Iterable[str] = ()) -> list[str]:
    """Probes for the interviewer: ask for whatever the answer did not cover."""
    return [*PROBES.values(), *extra][:4]


def next_competency(exclude_concepts: set[str]) -> str:
    """First competency in the rotation not yet asked; wraps around when all were used."""
    for key in ROTATION:
        if key not in exclude_concepts:
            return key
    return ROTATION[0]
