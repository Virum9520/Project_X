"""Arjuna's problem bank: problem families, public examples and hidden test cases.

Each problem has a trusted Python reference solution. Expected outputs are computed from it once
(lazily) so a test can never disagree with the statement, and a unit test runs the reference
through the real harness. Hidden cases carry a *label* (the category of the case) that Arjuna may
speak; their inputs and expected values are shown only when a case is marked `shareable`, which
is true for the public examples alone.

A problem belongs to a *family* (the underlying technique, e.g. "hash lookup for a complement").
Evidence cites the family so a new problem in the same family is not counted as transfer.
"""

import copy
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from heapq import heappop, heappush
from typing import Any

SUPPORTED_LANGUAGES: tuple[str, ...] = ("python", "javascript")
MAX_HINT_LEVEL = 3


@dataclass(frozen=True)
class Case:
    label: str
    args: list[Any]
    shareable: bool = False


@dataclass(frozen=True)
class Problem:
    id: str
    family: str
    concept_key: str
    title: str
    difficulty: int  # 1 easy, 2 medium, 3 hard
    statement: str
    function: str  # snake_case; JavaScript uses the camelCase form
    params: tuple[str, ...]
    reference: Callable[..., Any]
    examples: tuple[Case, ...]
    hidden: tuple[Case, ...]
    hints: tuple[str, str, str]
    time_limit_s: float = 2.0
    secondary_concepts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def js_function(self) -> str:
        return camel(self.function)


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


# ── Reference solutions (trusted) ─────────────────────────────────────────────────────────────


def _two_sum(nums: list[int], target: int) -> list[int]:
    seen: dict[int, int] = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
    return []


def _is_valid(s: str) -> bool:
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    for ch in s:
        if ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
        else:
            stack.append(ch)
    return not stack


def _min_meeting_rooms(intervals: list[list[int]]) -> int:
    ends: list[int] = []
    for start, end in sorted(intervals):
        if ends and ends[0] <= start:
            heappop(ends)
        heappush(ends, end)
    return len(ends)


def _merge(intervals: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out


def _search_rotated(nums: list[int], target: int) -> int:
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        if nums[lo] <= nums[mid]:
            if nums[lo] <= target < nums[mid]:
                hi = mid - 1
            else:
                lo = mid + 1
        elif nums[mid] < target <= nums[hi]:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1


def _longest_unique(s: str) -> int:
    last: dict[str, int] = {}
    best = start = 0
    for i, ch in enumerate(s):
        if ch in last and last[ch] >= start:
            start = last[ch] + 1
        last[ch] = i
        best = max(best, i - start + 1)
    return best


def _max_area(heights: list[int]) -> int:
    lo, hi, best = 0, len(heights) - 1, 0
    while lo < hi:
        best = max(best, min(heights[lo], heights[hi]) * (hi - lo))
        if heights[lo] < heights[hi]:
            lo += 1
        else:
            hi -= 1
    return best


def _subarray_sum(nums: list[int], k: int) -> int:
    seen = {0: 1}
    total = count = 0
    for n in nums:
        total += n
        count += seen.get(total - k, 0)
        seen[total] = seen.get(total, 0) + 1
    return count


def _num_islands(grid: list[list[int]]) -> int:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    seen = [[False] * cols for _ in range(rows)]
    count = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == 1 and not seen[r][c]:
                count += 1
                stack = [(r, c)]
                seen[r][c] = True
                while stack:
                    y, x = stack.pop()
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = y + dy, x + dx
                        inside = 0 <= ny < rows and 0 <= nx < cols
                        if inside and grid[ny][nx] == 1 and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((ny, nx))
    return count


def _shortest_path(grid: list[list[int]]) -> int:
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if not rows or grid[0][0] == 1 or grid[-1][-1] == 1:
        return -1
    dist = {(0, 0): 0}
    frontier = [(0, 0)]
    while frontier:
        nxt: list[tuple[int, int]] = []
        for y, x in frontier:
            if (y, x) == (rows - 1, cols - 1):
                return dist[(y, x)]
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < rows and 0 <= nx < cols and grid[ny][nx] == 0 and (ny, nx) not in dist:
                    dist[(ny, nx)] = dist[(y, x)] + 1
                    nxt.append((ny, nx))
        frontier = nxt
    return -1


def _coin_change(coins: list[int], amount: int) -> int:
    inf = amount + 1
    best = [0] + [inf] * amount
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a and best[a - c] + 1 < best[a]:
                best[a] = best[a - c] + 1
    return best[amount] if best[amount] != inf else -1


def _can_finish(num_courses: int, prerequisites: list[list[int]]) -> bool:
    indegree = [0] * num_courses
    after: list[list[int]] = [[] for _ in range(num_courses)]
    for course, before in prerequisites:
        after[before].append(course)
        indegree[course] += 1
    ready = [i for i, d in enumerate(indegree) if d == 0]
    done = 0
    while ready:
        node = ready.pop()
        done += 1
        for nxt in after[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return done == num_courses


def _daily_temperatures(temps: list[int]) -> list[int]:
    out = [0] * len(temps)
    stack: list[int] = []
    for i, t in enumerate(temps):
        while stack and temps[stack[-1]] < t:
            j = stack.pop()
            out[j] = i - j
        stack.append(i)
    return out


def _count_components(n: int, edges: list[list[int]]) -> int:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    components = n
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            components -= 1
    return components


# ── Case builders ─────────────────────────────────────────────────────────────────────────────


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _big_two_sum() -> Case:
    rng = _rng(11)
    nums = list(range(1, 60_001, 3))  # distinct and increasing; the two largest sum is unique
    target = nums[-1] + nums[-2]
    rng.shuffle(nums)
    return Case("large input (60 thousand numbers)", [nums, target])


def _big_intervals(n: int, seed: int) -> list[list[int]]:
    rng = _rng(seed)
    out = []
    for _ in range(n):
        start = rng.randrange(0, 1_000_000)
        out.append([start, start + rng.randrange(1, 500)])
    return out


def _big_grid(rows: int, cols: int, seed: int, density: float) -> list[list[int]]:
    rng = _rng(seed)
    return [[1 if rng.random() < density else 0 for _ in range(cols)] for _ in range(rows)]


def _big_temps() -> list[int]:
    rng = _rng(5)
    return [rng.randrange(30, 100) for _ in range(50_000)]


def _big_edges() -> list[list[int]]:
    rng = _rng(9)
    return [[rng.randrange(0, 20_000), rng.randrange(0, 20_000)] for _ in range(15_000)]


def _long_chain_courses(n: int) -> list[list[int]]:
    return [[i + 1, i] for i in range(n - 1)]


def _rotated(n: int, pivot: int) -> list[int]:
    base = list(range(10, 10 + 2 * n, 2))
    return base[pivot:] + base[:pivot]


# ── The bank ──────────────────────────────────────────────────────────────────────────────────

_PROBLEMS: tuple[Problem, ...] = (
    Problem(
        id="p_two_sum",
        family="complement_lookup",
        concept_key="dsa.hash_tables",
        title="Two Sum",
        difficulty=1,
        statement=(
            "Given a list of integers `nums` and an integer `target`, return the indices of the "
            "two numbers that add up to `target`, as a list `[i, j]` with `i < j`. Exactly one "
            "such pair exists, and you may not use the same element twice."
        ),
        function="two_sum",
        params=("nums", "target"),
        reference=_two_sum,
        examples=(
            Case("example 1", [[2, 7, 11, 15], 9], True),
            Case("example 2", [[3, 2, 4], 6], True),
        ),
        hidden=(
            Case("duplicate values", [[3, 3], 6]),
            Case("negative numbers", [[-1, -2, -3, -4, -5], -8]),
            Case("answer at the far end", [[1, 5, 9, 14, 20, 31], 51]),
            Case("zero in the input", [[0, 4, 3, 0], 0]),
            _big_two_sum(),
        ),
        hints=(
            "What do you need to have seen already, for the current number to complete a pair?",
            "Could a lookup structure remember earlier numbers so each check is constant time?",
            "Walk the list once, storing each value with its index, and check for target minus "
            "the current value before inserting it.",
        ),
    ),
    Problem(
        id="p_valid_parentheses",
        family="stack_matching",
        concept_key="dsa.stacks",
        title="Valid Parentheses",
        difficulty=1,
        statement=(
            "Given a string `s` of only the characters `()[]{}`, return whether the brackets "
            "are balanced: every opener is closed by the same kind of bracket, in the right "
            "order."
        ),
        function="is_valid",
        params=("s",),
        reference=_is_valid,
        examples=(
            Case("example 1", ["()[]{}"], True),
            Case("example 2", ["(]"], True),
        ),
        hidden=(
            Case("empty string", [""]),
            Case("nested", ["{[()]}"]),
            Case("closes in the wrong order", ["([)]"]),
            Case("starts with a closer", ["]["]),
            Case("unclosed opener", ["((("]),
            Case("large balanced input", ["(" * 20_000 + ")" * 20_000]),
        ),
        hints=(
            "When you meet a closing bracket, which opener must be the most recent unmatched one?",
            "That last-in-first-out behaviour suggests a particular data structure.",
            "Push openers on a stack; on a closer, pop and compare. At the end the stack must be "
            "empty.",
        ),
    ),
    Problem(
        id="p_meeting_rooms_2",
        family="sweep_with_heap",
        concept_key="dsa.heaps",
        title="Meeting Rooms II",
        difficulty=2,
        statement=(
            "Given a list of meeting time intervals `[start, end]` (end is exclusive), return "
            "the minimum number of rooms needed so that no two meetings in the same room "
            "overlap. A meeting ending at time `t` frees its room for one starting at `t`."
        ),
        function="min_meeting_rooms",
        params=("intervals",),
        reference=_min_meeting_rooms,
        examples=(
            Case("example 1", [[[0, 30], [5, 10], [15, 20]]], True),
            Case("example 2", [[[7, 10], [2, 4]]], True),
        ),
        hidden=(
            Case("no meetings", [[]]),
            Case("back to back meetings", [[[1, 5], [5, 10], [10, 15]]]),
            Case("all overlap", [[[1, 10], [2, 9], [3, 8], [4, 7]]]),
            Case("unsorted input", [[[15, 20], [0, 30], [5, 10], [12, 14]]]),
            Case("large input", [_big_intervals(30_000, 21)]),
        ),
        hints=(
            "At any moment, what do you need to know about the meetings currently running?",
            "When a new meeting starts, which running meeting is the first to end, and can its "
            "room be reused?",
            "Sort by start time and keep a min-heap of end times; reuse a room when the "
            "earliest end is at most the new start, otherwise add one.",
        ),
    ),
    Problem(
        id="p_merge_intervals",
        family="sort_then_merge",
        concept_key="dsa.intervals",
        title="Merge Intervals",
        difficulty=2,
        statement=(
            "Given a list of closed intervals `[start, end]`, merge all overlapping intervals "
            "(touching ends count as overlapping) and return the merged intervals sorted by "
            "start."
        ),
        function="merge",
        params=("intervals",),
        reference=_merge,
        examples=(
            Case("example 1", [[[1, 3], [2, 6], [8, 10], [15, 18]]], True),
            Case("example 2", [[[1, 4], [4, 5]]], True),
        ),
        hidden=(
            Case("single interval", [[[5, 7]]]),
            Case("unsorted input", [[[8, 10], [1, 3], [2, 6], [15, 18]]]),
            Case("one interval swallows the rest", [[[1, 20], [2, 3], [4, 5], [6, 7]]]),
            Case("chain of overlaps", [[[1, 2], [2, 3], [3, 4], [4, 5]]]),
            Case("large input", [_big_intervals(40_000, 33)]),
        ),
        hints=(
            "What order would make overlapping intervals neighbours?",
            "After sorting, when does the current interval overlap the last merged one?",
            "Sort by start; extend the last merged interval's end when the next start is at "
            "most that end, otherwise append a new interval.",
        ),
    ),
    Problem(
        id="p_search_rotated",
        family="binary_search_on_structure",
        concept_key="dsa.binary_search",
        title="Search in a Rotated Sorted Array",
        difficulty=2,
        statement=(
            "A sorted list of distinct integers was rotated at an unknown pivot, for example "
            "`[4, 5, 6, 7, 0, 1, 2]`. Given `nums` and a `target`, return the index of `target` "
            "or `-1`. Aim for O(log n) time."
        ),
        function="search",
        params=("nums", "target"),
        reference=_search_rotated,
        examples=(
            Case("example 1", [[4, 5, 6, 7, 0, 1, 2], 0], True),
            Case("example 2", [[4, 5, 6, 7, 0, 1, 2], 3], True),
        ),
        hidden=(
            Case("single element found", [[1], 1]),
            Case("single element missing", [[1], 0]),
            Case("not rotated", [[1, 2, 3, 4, 5], 4]),
            Case("two elements", [[3, 1], 1]),
            Case("target is the pivot value", [[6, 7, 1, 2, 3, 4, 5], 1]),
            Case("large input", [_rotated(200_000, 77_777), 10 + 2 * 150_000]),
        ),
        time_limit_s=1.0,
        hints=(
            "After you look at the middle element, is at least one half of the list still "
            "sorted? How can you tell?",
            "Check whether the target lies inside the sorted half; if so go there, otherwise "
            "go to the other half.",
            "Compare nums[lo] with nums[mid] to find the sorted half, then test the target "
            "against that half's range.",
        ),
    ),
    Problem(
        id="p_longest_unique_substring",
        family="variable_window",
        concept_key="dsa.sliding_window",
        title="Longest Substring Without Repeating Characters",
        difficulty=2,
        statement=(
            "Given a string `s`, return the length of the longest substring that has no "
            "repeated characters."
        ),
        function="length_of_longest_substring",
        params=("s",),
        reference=_longest_unique,
        examples=(
            Case("example 1", ["abcabcbb"], True),
            Case("example 2", ["bbbbb"], True),
        ),
        hidden=(
            Case("empty string", [""]),
            Case("all distinct", ["abcdef"]),
            Case("repeat inside the window", ["abba"]),
            Case("repeat far apart", ["tmmzuxt"]),
            Case("large input", ["".join(chr(97 + (i * 7) % 26) for i in range(100_000))]),
        ),
        hints=(
            "If you track a window of unique characters, what must happen when a repeat arrives?",
            "Where should the left edge of the window move to when the new character was "
            "already seen inside it?",
            "Keep a map from character to last index; on a repeat inside the window move the "
            "start to one past that index, and update the best length each step.",
        ),
    ),
    Problem(
        id="p_container_water",
        family="two_pointer_shrink",
        concept_key="dsa.two_pointers",
        title="Container With Most Water",
        difficulty=2,
        statement=(
            "Each integer in `heights` is the height of a vertical line at that index. Choose "
            "two lines that, with the x-axis, form a container; return the largest amount of "
            "water it can hold (width times the shorter height)."
        ),
        function="max_area",
        params=("heights",),
        reference=_max_area,
        examples=(
            Case("example 1", [[1, 8, 6, 2, 5, 4, 8, 3, 7]], True),
            Case("example 2", [[1, 1]], True),
        ),
        hidden=(
            Case("increasing heights", [[1, 2, 3, 4, 5, 6]]),
            Case("tall lines at the ends", [[9, 1, 1, 1, 1, 9]]),
            Case("zeros", [[0, 0, 5, 0, 0]]),
            Case("large input", [[(i * 37) % 1000 for i in range(80_000)]]),
        ),
        hints=(
            "Start with the widest container. What is the only way to get a larger area from "
            "a narrower one?",
            "Which of the two lines limits the height, and is moving the taller line ever useful?",
            "Use two pointers at the ends; always move the pointer at the shorter line inward, "
            "tracking the best area.",
        ),
    ),
    Problem(
        id="p_subarray_sum_k",
        family="prefix_sum_lookup",
        concept_key="dsa.prefix_sums",
        title="Subarray Sum Equals K",
        difficulty=2,
        statement=(
            "Given a list of integers `nums` (which may include negatives) and an integer `k`, "
            "return how many contiguous subarrays sum to `k`."
        ),
        function="subarray_sum",
        params=("nums", "k"),
        reference=_subarray_sum,
        examples=(
            Case("example 1", [[1, 1, 1], 2], True),
            Case("example 2", [[1, 2, 3], 3], True),
        ),
        hidden=(
            Case("negative numbers", [[1, -1, 0], 0]),
            Case("single element", [[5], 5]),
            Case("no match", [[1, 2, 3], 100]),
            Case("many zeros", [[0] * 40, 0]),
            Case("large input", [[(i % 7) - 3 for i in range(100_000)], 4]),
        ),
        hints=(
            "How would you get the sum of any subarray from running totals?",
            "If the running total now is S, which earlier running total would make this "
            "subarray sum to k?",
            "Keep a map from prefix sum to how many times it occurred; add the count for "
            "S minus k at each step.",
        ),
    ),
    Problem(
        id="p_number_of_islands",
        family="flood_fill_components",
        concept_key="dsa.dfs",
        title="Number of Islands",
        difficulty=2,
        statement=(
            "Given a grid of `1` (land) and `0` (water), return the number of islands. An "
            "island is land connected horizontally or vertically."
        ),
        function="num_islands",
        params=("grid",),
        reference=_num_islands,
        examples=(
            Case("example 1", [[[1, 1, 0, 0], [1, 0, 0, 1], [0, 0, 1, 1]]], True),
            Case("example 2", [[[1, 0, 1], [0, 1, 0], [1, 0, 1]]], True),
        ),
        hidden=(
            Case("empty grid", [[]]),
            Case("all water", [[[0, 0], [0, 0]]]),
            Case("all land", [[[1, 1], [1, 1]]]),
            Case("snake shaped island", [[[1, 1, 1], [0, 0, 1], [1, 1, 1], [1, 0, 0], [1, 1, 1]]]),
            Case("large grid", [_big_grid(60, 60, 3, 0.5)]),
        ),
        hints=(
            "Once you find a piece of land, what should happen to the rest of its island so "
            "you never count it twice?",
            "A traversal from that cell can mark every connected land cell as visited.",
            "Scan every cell; on unvisited land, increment the count and run a DFS or BFS "
            "marking connected land. Use an explicit stack if recursion could get deep.",
        ),
        secondary_concepts=("dsa.bfs",),
    ),
    Problem(
        id="p_shortest_path_grid",
        family="bfs_shortest_path",
        concept_key="dsa.bfs",
        title="Shortest Path in a Grid",
        difficulty=2,
        statement=(
            "In a grid of `0` (open) and `1` (wall), find the fewest steps from the top-left "
            "to the bottom-right cell, moving up, down, left or right. Return `-1` if there "
            "is no path. The number of steps for a 1x1 open grid is `0`."
        ),
        function="shortest_path",
        params=("grid",),
        reference=_shortest_path,
        examples=(
            Case("example 1", [[[0, 0, 0], [1, 1, 0], [0, 0, 0]]], True),
            Case("example 2", [[[0, 1], [1, 0]]], True),
        ),
        hidden=(
            Case("single open cell", [[[0]]]),
            Case("start is a wall", [[[1, 0], [0, 0]]]),
            Case("open grid", [[[0] * 6 for _ in range(6)]]),
            Case("winding corridor", [[[0, 1, 0, 0, 0], [0, 1, 0, 1, 0], [0, 0, 0, 1, 0]]]),
            Case("large open grid", [[[0] * 400 for _ in range(400)]]),
        ),
        hints=(
            "You want the fewest steps. Which traversal explores cells in order of distance?",
            "Process cells level by level; what must you remember so you never revisit a cell?",
            "Breadth-first search from the start with a visited set; the level at which you "
            "reach the end is the answer.",
        ),
        secondary_concepts=("dsa.dfs",),
    ),
    Problem(
        id="p_coin_change",
        family="unbounded_knapsack_dp",
        concept_key="dsa.dynamic_programming",
        title="Coin Change",
        difficulty=3,
        statement=(
            "Given coin denominations `coins` and a target `amount`, return the fewest coins "
            "that sum to `amount`, or `-1` if it is impossible. You have unlimited coins of "
            "each denomination."
        ),
        function="coin_change",
        params=("coins", "amount"),
        reference=_coin_change,
        examples=(
            Case("example 1", [[1, 2, 5], 11], True),
            Case("example 2", [[2], 3], True),
        ),
        hidden=(
            Case("amount zero", [[1], 0]),
            Case("greedy fails", [[1, 3, 4], 6]),
            Case("impossible", [[5, 10], 7]),
            Case("single coin exact", [[7], 49]),
            Case("large amount", [[1, 5, 10, 25, 50], 9_000]),
        ),
        hints=(
            "What is the answer for amount 0, and how does the answer for amount a relate to "
            "smaller amounts?",
            "If you use one coin c last, how many coins did the rest need?",
            "Let best[a] be the fewest coins for a. best[a] = 1 + min(best[a - c]) over coins "
            "c <= a. Build it up from 0.",
        ),
        time_limit_s=3.0,
    ),
    Problem(
        id="p_course_schedule",
        family="cycle_detection_topological",
        concept_key="dsa.topological_sort",
        title="Course Schedule",
        difficulty=2,
        statement=(
            "There are `num_courses` courses labelled `0..num_courses-1`. Each pair "
            "`[a, b]` in `prerequisites` means course `b` must be taken before course `a`. "
            "Return whether all courses can be finished."
        ),
        function="can_finish",
        params=("num_courses", "prerequisites"),
        reference=_can_finish,
        examples=(
            Case("example 1", [2, [[1, 0]]], True),
            Case("example 2", [2, [[1, 0], [0, 1]]], True),
        ),
        hidden=(
            Case("no prerequisites", [4, []]),
            Case("longer cycle", [4, [[1, 0], [2, 1], [3, 2], [1, 3]]]),
            Case("diamond, no cycle", [4, [[1, 0], [2, 0], [3, 1], [3, 2]]]),
            Case("disconnected with a cycle", [5, [[1, 0], [3, 4], [4, 3]]]),
            Case("large chain of courses", [800, _long_chain_courses(800)]),
        ),
        hints=(
            "When is it impossible to finish every course? What does that look like as a graph?",
            "Which courses can you take first? What changes after you take one?",
            "Count incoming prerequisites per course, repeatedly take courses with none, and "
            "compare how many you took with the total (Kahn's algorithm).",
        ),
    ),
    Problem(
        id="p_daily_temperatures",
        family="next_greater_stack",
        concept_key="dsa.monotonic_stack",
        title="Daily Temperatures",
        difficulty=2,
        statement=(
            "Given daily `temps`, return a list where entry `i` is the number of days to wait "
            "after day `i` for a warmer temperature, or `0` if none will come."
        ),
        function="daily_temperatures",
        params=("temps",),
        reference=_daily_temperatures,
        examples=(
            Case("example 1", [[73, 74, 75, 71, 69, 72, 76, 73]], True),
            Case("example 2", [[30, 40, 50, 60]], True),
        ),
        hidden=(
            Case("single day", [[50]]),
            Case("decreasing", [[90, 80, 70, 60]]),
            Case("equal temperatures", [[70, 70, 70]]),
            Case("large input", [_big_temps()]),
        ),
        hints=(
            "For each day, which earlier days are still waiting for something warmer?",
            "Those waiting days, in order, have a particular monotone shape of temperatures.",
            "Keep a stack of indices with decreasing temperatures; when today is warmer, pop "
            "indices and set their wait to the index difference.",
        ),
    ),
    Problem(
        id="p_connected_components",
        family="union_find_components",
        concept_key="dsa.union_find",
        title="Number of Connected Components",
        difficulty=2,
        statement=(
            "Given `n` nodes labelled `0..n-1` and a list of undirected `edges`, return the "
            "number of connected components."
        ),
        function="count_components",
        params=("n", "edges"),
        reference=_count_components,
        examples=(
            Case("example 1", [5, [[0, 1], [1, 2], [3, 4]]], True),
            Case("example 2", [4, [[0, 1], [2, 3], [1, 2]]], True),
        ),
        hidden=(
            Case("no edges", [5, []]),
            Case("single node", [1, []]),
            Case("duplicate and cyclic edges", [4, [[0, 1], [1, 0], [1, 2], [2, 0]]]),
            Case("large input", [20_000, _big_edges()]),
        ),
        hints=(
            "If you merge two nodes, how does the number of components change?",
            "You need to know quickly whether two nodes are already in the same component.",
            "Use union-find with path compression: start with n components and subtract one "
            "each time a union joins two different roots.",
        ),
        secondary_concepts=("dsa.dfs",),
    ),
)

BY_ID: dict[str, Problem] = {p.id: p for p in _PROBLEMS}
ALL_PROBLEMS: tuple[Problem, ...] = _PROBLEMS


def get_problem(problem_id: str) -> Problem | None:
    return BY_ID.get(problem_id)


def problems_for_concept(concept_key: str) -> list[Problem]:
    own = [p for p in _PROBLEMS if p.concept_key == concept_key]
    related = [p for p in _PROBLEMS if concept_key in p.secondary_concepts]
    return sorted(own, key=lambda p: p.difficulty) + sorted(related, key=lambda p: p.difficulty)


def select_problem(
    concept_key: str | None,
    *,
    difficulty: str = "same",
    exclude: set[str] | frozenset[str] = frozenset(),
    exclude_families: set[str] | frozenset[str] = frozenset(),
) -> tuple[Problem, bool]:
    """Pick the next problem. Returns `(problem, matched_concept)`.

    Unused problems come first; among them a family not yet seen is preferred (so a second
    problem is a real transfer test). `difficulty` biases towards easier or harder.
    """
    candidates = problems_for_concept(concept_key) if concept_key else []
    matched = bool(candidates)
    if not candidates:
        candidates = sorted(_PROBLEMS, key=lambda p: (p.difficulty, p.id))
    fresh = [p for p in candidates if p.id not in exclude] or candidates
    new_family = [p for p in fresh if p.family not in exclude_families] or fresh
    if difficulty == "easier":
        new_family = sorted(new_family, key=lambda p: p.difficulty)
    elif difficulty == "harder":
        new_family = sorted(new_family, key=lambda p: -p.difficulty)
    return new_family[0], matched


# ── Views, starter code, expected values ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class

    index: int
    label: str
    args: list[Any]
    expected: Any
    shareable: bool


@cache
def cases_for(problem_id: str) -> tuple[TestCase, ...]:
    """Public examples then hidden cases, with expected values from the reference solution."""
    problem = BY_ID[problem_id]
    out: list[TestCase] = []
    for i, case in enumerate((*problem.examples, *problem.hidden)):
        # The reference may mutate its input (merge, etc.), so give it a deep copy.
        expected = problem.reference(*copy.deepcopy(case.args))
        out.append(TestCase(i, case.label, case.args, expected, case.shareable))
    return tuple(out)


def starter_code(problem: Problem, language: str) -> str:
    if language == "javascript":
        args = ", ".join(problem.params)
        return (
            f"// {problem.title}\n"
            f"function {problem.js_function}({args}) {{\n"
            "  // Write your solution here.\n"
            "}\n"
        )
    args = ", ".join(problem.params)
    return (
        f'"""{problem.title}"""\n\n\n'
        f"def {problem.function}({args}):\n"
        "    # Write your solution here.\n"
        "    pass\n"
    )


def public_examples(problem: Problem) -> list[dict[str, Any]]:
    cases = cases_for(problem.id)
    return [
        {
            "label": c.label,
            "input": {name: value for name, value in zip(problem.params, c.args, strict=True)},
            "expected": c.expected,
        }
        for c in cases
        if c.shareable
    ]


_SAFE_ID = re.compile(r"^p_[a-z0-9_]{1,60}$")


def is_problem_id(value: str) -> bool:
    return bool(_SAFE_ID.match(value))
