from drona_fixtures import BINARY_SEARCH

from sg_api.drona.questions import (
    parse_exclusions,
    parse_question_id,
    question_id,
    select_question,
)


def test_question_ids_round_trip() -> None:
    qid = question_id("teach_back", "dsa.binary_search", 0)
    assert qid == "teach_back:dsa.binary_search:0"
    assert parse_question_id(qid) == ("teach_back", "dsa.binary_search", 0)
    assert parse_question_id("nonsense") is None
    assert parse_question_id("a:b:c") is None


def test_concept_check_turns_criteria_into_spoken_questions() -> None:
    first = select_question(BINARY_SEARCH, "concept_check")
    assert first.question_id.endswith(":0")
    assert "Binary search" in first.prompt
    second = select_question(BINARY_SEARCH, "concept_check", exclude={first.question_id})
    assert second.question_id.endswith(":1")
    assert second.prompt == "Can you explain why the input must be sorted?"
    assert second.hints == ["Explains why the input must be sorted"]


def test_repeats_when_everything_was_used() -> None:
    seen: set[str] = set()
    for _ in range(3):
        q = select_question(BINARY_SEARCH, "concept_check", exclude=seen)
        seen.add(q.question_id)
    again = select_question(BINARY_SEARCH, "concept_check", exclude=seen)
    assert again.repeat


def test_teach_back_voices_misconceptions_for_the_agent_only() -> None:
    q = select_question(BINARY_SEARCH, "teach_back")
    assert q.kind == "teach_back"
    assert q.hints == ["Binary search works on any list"]
    assert "Binary search works on any list" not in q.prompt


def test_cross_question_includes_misconception_probe_and_difficulty_start() -> None:
    easy = select_question(BINARY_SEARCH, "cross_question", difficulty="easier")
    hard = select_question(BINARY_SEARCH, "cross_question", difficulty="harder")
    assert easy.question_id != hard.question_id


def test_exclusion_parsing_ignores_blanks() -> None:
    assert parse_exclusions(" a , ,b ") == {"a", "b"}
    assert parse_exclusions(None) == set()
