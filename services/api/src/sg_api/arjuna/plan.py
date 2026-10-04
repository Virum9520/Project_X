"""Turn an uploaded résumé and job description into an interview plan.

The parse is deterministic: a lexicon of technical terms mapped to curriculum concepts, counted
in the document text. No model reads the documents, so nothing in them can steer the interview.
What the plan carries:

- `claims`: concepts the résumé mentions. These are **self-reported**: they decide what Arjuna
  asks about, never what the learner is credited with. Only demonstrated answers grow the garden.
- `requirements`: concepts the job description asks for.
- `probes`: the concepts to cover, job-description requirements first, then résumé claims, then
  fundamentals as filler, restricted to concepts that exist in the active curriculum.
- `projects`: a few résumé lines (clipped, stripped of markup) Arjuna may ask a follow-up about.
  Lines that look like instructions to an AI are dropped.
- `problems`: suggested problem IDs from the bank for the top probes.

Everything here is pure; the database read lives in `sg_api.arjuna.store`.
"""

import re
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field

from sg_api.arjuna.problems import problems_for_concept

MAX_TEXT_CHARS = 60_000
MAX_PROBES = 6
MAX_PROJECTS = 3
MAX_PROBLEMS = 4

# concept key -> phrases (matched on word boundaries, case-insensitive). Terms are deliberately
# specific: "tree" alone would match "decision tree".
LEXICON: dict[str, tuple[str, ...]] = {
    "dsa.big_o": ("big-o", "big o", "time complexity", "algorithmic complexity"),
    "dsa.arrays": ("arrays", "array manipulation"),
    "dsa.strings": ("string manipulation", "string processing", "string algorithms"),
    "dsa.linked_lists": ("linked list", "linked lists"),
    "dsa.stacks": ("stack", "stacks"),
    "dsa.queues": ("queue", "queues", "deque"),
    "dsa.hash_tables": (
        "hash map",
        "hash maps",
        "hashmap",
        "hashmaps",
        "hash table",
        "hash tables",
        "dictionaries",
    ),
    "dsa.two_pointers": ("two pointers", "two-pointer"),
    "dsa.sliding_window": ("sliding window",),
    "dsa.prefix_sums": ("prefix sum", "prefix sums"),
    "dsa.binary_search": ("binary search",),
    "dsa.recursion": ("recursion", "recursive algorithms"),
    "dsa.sorting": ("sorting algorithms", "quicksort", "mergesort", "merge sort", "heapsort"),
    "dsa.monotonic_stack": ("monotonic stack",),
    "dsa.intervals": ("interval scheduling", "intervals"),
    "dsa.binary_trees": ("binary tree", "binary trees", "tree traversal"),
    "dsa.binary_search_trees": ("binary search tree", "bst"),
    "dsa.balanced_trees": ("avl tree", "red-black tree", "b-tree", "balanced tree"),
    "dsa.heaps": ("heap", "heaps", "priority queue", "priority queues"),
    "dsa.tries": ("trie", "tries", "prefix tree"),
    "dsa.graph_representation": ("adjacency list", "adjacency matrix", "graph algorithms"),
    "dsa.bfs": ("bfs", "breadth-first", "breadth first"),
    "dsa.dfs": ("dfs", "depth-first", "depth first"),
    "dsa.topological_sort": ("topological sort", "topological ordering", "dependency graph"),
    "dsa.shortest_paths": ("dijkstra", "shortest path", "bellman-ford", "a* search"),
    "dsa.union_find": ("union-find", "union find", "disjoint set"),
    "dsa.backtracking": ("backtracking",),
    "dsa.greedy": ("greedy algorithm", "greedy algorithms"),
    "dsa.dynamic_programming": ("dynamic programming", "memoization"),
    "dsa.dp_patterns": ("knapsack", "longest common subsequence"),
    "databases.relational_model": ("relational database", "sql", "postgres", "postgresql", "mysql"),
    "databases.indexes": ("database index", "indexing", "b-tree index"),
    "databases.transactions_acid": ("acid", "transactions"),
    "databases.nosql_models": ("nosql", "mongodb", "dynamodb", "cassandra", "redis"),
    "databases.replication": ("replication",),
    "databases.partitioning": ("sharding", "partitioning"),
    "os.processes_threads": ("multithreading", "multi-threading", "concurrency", "threads"),
    "os.synchronization": ("mutex", "semaphore", "locks"),
    "os.deadlocks": ("deadlock", "deadlocks"),
    "os.async_io": ("async", "asynchronous", "event loop", "non-blocking"),
    "networks.tcp": ("tcp", "tcp/ip"),
    "networks.http": ("http", "rest api", "rest apis", "restful"),
    "networks.dns": ("dns",),
    "networks.tls": ("tls", "ssl", "https"),
    "system_design.scalability": ("scalability", "scalable systems", "distributed systems"),
    "system_design.load_balancing": ("load balancer", "load balancing"),
    "system_design.caching": ("caching", "cache"),
    "system_design.message_queues": ("kafka", "rabbitmq", "message queue", "sqs", "pub/sub"),
    "system_design.rate_limiting": ("rate limiting", "rate limiter"),
    "system_design.api_design": ("api design", "graphql", "grpc"),
    "system_design.observability": ("observability", "monitoring", "prometheus", "grafana"),
}

# Fundamentals to fill an interview when the documents say little.
FALLBACK_PROBES: tuple[str, ...] = (
    "dsa.hash_tables",
    "dsa.two_pointers",
    "dsa.binary_search",
    "dsa.bfs",
)

_ACTION_LINE = re.compile(
    r"\b(built|developed|implemented|designed|created|led|architected|shipped|optimi[sz]ed|"
    r"reduced|improved|wrote|launched)\b",
    re.IGNORECASE,
)
_INSTRUCTION_LIKE = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above)|disregard|you are now|"
    r"new instructions|system prompt|as an ai|<\s*/?\s*(?:system|assistant|tool)\b|"
    r"\bassistant\s*:|\bsystem\s*:|reveal|jailbreak|pretend",
    re.IGNORECASE,
)
_MARKUP = re.compile(r"[<>{}`\[\]\\|]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # keeps tab and newline
_BULLETS = re.compile(r"^[\s\-*•·▪●◦>\d.)]+")


@dataclass(frozen=True)
class Mention:
    concept_key: str
    count: int


@dataclass(frozen=True)
class InterviewPlan:
    role: str
    has_resume: bool
    has_job_description: bool
    claims: tuple[Mention, ...] = field(default_factory=tuple)
    requirements: tuple[Mention, ...] = field(default_factory=tuple)
    probes: tuple[str, ...] = field(default_factory=tuple)
    projects: tuple[str, ...] = field(default_factory=tuple)
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def grounded(self) -> bool:
        """True when the plan came from the learner's documents rather than the defaults."""
        return bool(self.claims or self.requirements)


def _clean(text: str) -> str:
    return _CONTROL.sub(" ", text)[:MAX_TEXT_CHARS]


def _pattern(phrases: tuple[str, ...]) -> re.Pattern[str]:
    escaped = [re.escape(p) for p in sorted(phrases, key=len, reverse=True)]
    return re.compile(r"(?<![\w-])(?:" + "|".join(escaped) + r")(?![\w-])", re.IGNORECASE)


_PATTERNS: dict[str, re.Pattern[str]] = {key: _pattern(p) for key, p in LEXICON.items()}


def count_mentions(text: str, known: Collection[str] | None = None) -> list[Mention]:
    """Concepts mentioned in `text`, most mentioned first (ties by concept key)."""
    body = _clean(text)
    counts: Counter[str] = Counter()
    for key, pattern in _PATTERNS.items():
        if known is not None and key not in known:
            continue
        hits = len(pattern.findall(body))
        if hits:
            counts[key] = hits
    return [Mention(k, n) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def project_lines(resume_text: str) -> list[str]:
    """Up to a few short résumé lines about things the learner says they built."""
    out: list[str] = []
    for raw in _clean(resume_text).splitlines():
        line = _BULLETS.sub("", raw).strip()
        if not 25 <= len(line) <= 220 or not _ACTION_LINE.search(line):
            continue
        if _INSTRUCTION_LIKE.search(line):
            continue
        line = " ".join(_MARKUP.sub(" ", line).split())
        if line and line not in out:
            out.append(line)
        if len(out) >= MAX_PROJECTS:
            break
    return out


def build_plan(
    *,
    resume_text: str | None,
    job_description_text: str | None,
    role: str,
    concept_keys: Collection[str],
) -> InterviewPlan:
    """Plan an interview. `concept_keys` are the active curriculum's concepts: anything else is
    never planned."""
    known = set(concept_keys)
    claims = count_mentions(resume_text, known) if resume_text else []
    requirements = count_mentions(job_description_text, known) if job_description_text else []

    probes: list[str] = []

    def add(key: str) -> None:
        if key in known and key not in probes and len(probes) < MAX_PROBES:
            probes.append(key)

    # Concepts with a coding problem come first: this is a coding interview. Within each source,
    # most mentioned first; requirements before claims.
    ordered = [m.concept_key for m in requirements] + [m.concept_key for m in claims]
    for key in ordered:
        if problems_for_concept(key):
            add(key)
    for key in ordered:
        add(key)  # discussion topics (databases, systems) after the coding ones
    for key in FALLBACK_PROBES:
        add(key)

    problems: list[str] = []
    for key in probes:
        for p in problems_for_concept(key)[:1]:
            if p.id not in problems and len(problems) < MAX_PROBLEMS:
                problems.append(p.id)
    return InterviewPlan(
        role=role,
        has_resume=bool(resume_text and resume_text.strip()),
        has_job_description=bool(job_description_text and job_description_text.strip()),
        claims=tuple(claims[:MAX_PROBES]),
        requirements=tuple(requirements[:MAX_PROBES]),
        probes=tuple(probes),
        projects=tuple(project_lines(resume_text) if resume_text else ()),
        problems=tuple(problems),
    )


def render_for_agent(plan: InterviewPlan) -> str:
    """The `interview_plan` dynamic variable: short, structured, labelled as data."""
    lines = [
        f"Target role: {plan.role}.",
        "Source: "
        + (
            ", ".join(
                s
                for s, present in (
                    ("résumé", plan.has_resume),
                    ("job description", plan.has_job_description),
                )
                if present
            )
            or "no résumé or job description uploaded; use fundamentals"
        )
        + ".",
    ]
    if plan.requirements:
        lines.append(
            "Job description asks for: " + ", ".join(m.concept_key for m in plan.requirements) + "."
        )
    if plan.claims:
        lines.append(
            "Résumé mentions (self-reported, unverified; ask, never assume): "
            + ", ".join(m.concept_key for m in plan.claims)
            + "."
        )
    lines.append("Cover in this order: " + ", ".join(plan.probes) + ".")
    if plan.problems:
        lines.append(
            "Suggested problems (confirm each with fetch_question): " + ", ".join(plan.problems)
        )
    if plan.projects:
        lines.append("Résumé project lines to ask one follow-up about (quoted data):")
        lines.extend(f'- "{p}"' for p in plan.projects)
    return "\n".join(lines)
