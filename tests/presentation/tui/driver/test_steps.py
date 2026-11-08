"""Script line parsing: verbs, keywords, typed errors."""

from __future__ import annotations

import pytest

from caio_code.presentation.tui.driver.errors import ScriptError
from caio_code.presentation.tui.driver.steps import (
    STEP_VERBS,
    AssertFooter,
    AssertText,
    AssertTodo,
    AssertWidget,
    Key,
    Send,
    Snapshot,
    Type,
    Wait,
    parse_line,
    parse_script,
)

pytestmark = pytest.mark.tui


class TestParseLine:
    def test_every_verb_parses(self) -> None:
        assert parse_line("type hello") == Type("hello")
        assert parse_line("key enter") == Key("enter")
        assert parse_line("wait 50") == Wait(50)
        assert parse_line("send fix the bug") == Send("fix the bug")
        assert parse_line("assert-text Done") == AssertText("Done")
        assert parse_line("assert-todo completed=2") == AssertTodo(completed=2)
        assert parse_line("assert-footer cache") == AssertFooter(contains=("cache",))
        assert parse_line("snapshot after-send") == Snapshot("after-send")
        assert parse_line("assert-widget #transcript") == AssertWidget("#transcript")

    def test_assert_text_with_within_keyword(self) -> None:
        step = parse_line("assert-text within=#transcript Done and done")
        assert step == AssertText(expected="Done and done", within="#transcript")

    def test_assert_todo_all_fields(self) -> None:
        step = parse_line("assert-todo count=5 in_progress=1 completed=2")
        assert step == AssertTodo(count=5, in_progress=1, completed=2)

    def test_assert_footer_multiple_words(self) -> None:
        step = parse_line("assert-footer OVER BUDGET")
        assert step == AssertFooter(contains=("OVER", "BUDGET"))

    def test_assert_widget_exists_false(self) -> None:
        step = parse_line("assert-widget #sidebar exists=false")
        assert step == AssertWidget(query="#sidebar", exists=False)

    def test_quoted_expected_text_keeps_single_token(self) -> None:
        step = parse_line('assert-text "2/5 · 40%"')
        assert step == AssertText(expected="2/5 · 40%")

    def test_unknown_verb_raises_script_error_naming_it(self) -> None:
        with pytest.raises(ScriptError, match="unknown step verb 'frobnicate'"):
            parse_line("frobnicate now")

    def test_unknown_verb_error_lists_known_verbs(self) -> None:
        with pytest.raises(ScriptError) as excinfo:
            parse_line("nope")
        for verb in STEP_VERBS:
            assert verb in str(excinfo.value)

    def test_missing_argument_raises(self) -> None:
        for verb in ("type", "key", "wait", "send", "snapshot"):
            with pytest.raises(ScriptError, match="needs an argument"):
                parse_line(verb)

    def test_wait_rejects_non_integer(self) -> None:
        with pytest.raises(ScriptError, match="integer"):
            parse_line("wait soon")

    def test_snapshot_rejects_unsafe_name(self) -> None:
        with pytest.raises(ScriptError, match="snapshot name"):
            parse_line("snapshot ../escape")

    def test_empty_and_comment_lines_are_not_steps(self) -> None:
        with pytest.raises(ScriptError):
            parse_line("")
        with pytest.raises(ScriptError):
            parse_line("# comment")

    def test_line_number_is_reported(self) -> None:
        with pytest.raises(ScriptError, match="line 7"):
            parse_line("bogus verb", line_number=7)


class TestParseScript:
    def test_skips_comments_and_blank_lines(self) -> None:
        text = "# plan\n\nsend hello\n\nwait 20\n"
        assert parse_script(text) == [Send("hello"), Wait(20)]

    def test_empty_script_is_rejected(self) -> None:
        with pytest.raises(ScriptError, match="no steps"):
            parse_script("# nothing\n")

    def test_error_carries_line_number(self) -> None:
        with pytest.raises(ScriptError, match="line 2"):
            parse_script("send hello\nbogus line\n")
