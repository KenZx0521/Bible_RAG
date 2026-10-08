"""--ids-file: a JSON list or one id per line; empty, malformed or unknown ids are refused."""

import pytest

from src.data_loader import load_gt
from src.id_selection import IdsFileError, parse_ids_text, read_ids_file, select_questions


@pytest.mark.parametrize("text", ['["B_002", "A_001", "B_002"]', "B_002\n\n A_001 \nB_002\n"],
                         ids=["json_list", "one_per_line"])
def test_ids_keep_file_order_and_count_once(text):
    assert parse_ids_text(text) == ("B_002", "A_001")


@pytest.mark.parametrize("text, match", [
    ("", "no question ids"),
    ("  \n\n", "no question ids"),
    ("[]", "no question ids"),
    ('["A_001", 2]', "non-empty strings"),
    ('["A_001", " "]', "non-empty strings"),
    ('["A_001",', "not a JSON list"),
    ('{"ids": ["A_001"]}', "JSON object"),
], ids=["empty", "blank", "empty_list", "non_string", "blank_string", "broken_json", "object"])
def test_empty_or_malformed_files_are_refused(text, match):
    with pytest.raises(IdsFileError, match=match):
        parse_ids_text(text)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(IdsFileError, match="cannot read"):
        read_ids_file(tmp_path / "nope.txt")


def test_read_ids_file_parses_the_file(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("VERSE_LOOKUP_002\nVERSE_LOOKUP_001\n", encoding="utf-8")

    assert read_ids_file(path) == ("VERSE_LOOKUP_002", "VERSE_LOOKUP_001")


def test_selection_follows_gt_order_and_all_without_ids():
    items = load_gt("v2").items

    chosen = select_questions(items, ("EVENT_QUESTION_041", "VERSE_LOOKUP_001"))

    assert [i.question_id for i in chosen] == ["VERSE_LOOKUP_001", "EVENT_QUESTION_041"]
    assert select_questions(items, None) == list(items)


def test_selection_refuses_ids_the_gt_lacks():
    with pytest.raises(IdsFileError, match="NOPE_001"):
        select_questions(load_gt("v2").items, ("VERSE_LOOKUP_001", "NOPE_001"))
