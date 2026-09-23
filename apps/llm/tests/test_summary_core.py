import pytest

from summary_core import SummaryInputTooShort, build_summary_prompt, prepare_summary_text


def test_prepare_summary_text_strips_and_truncates():
    assert prepare_summary_text("  " + ("가" * 151) + "  ", minimum=150, maximum=150) == "가" * 150


def test_prepare_summary_text_rejects_short_input():
    with pytest.raises(SummaryInputTooShort) as exc_info:
        prepare_summary_text("가" * 149, minimum=150, maximum=8000)

    assert exc_info.value.actual == 149
    assert exc_info.value.minimum == 150


@pytest.mark.parametrize(("character_count", "raises"), [(149, True), (150, False)])
def test_prepare_summary_text_excludes_whitespace_from_minimum_length(character_count, raises):
    text = "가 " * character_count

    if raises:
        with pytest.raises(SummaryInputTooShort) as exc_info:
            prepare_summary_text(text, minimum=150, maximum=8000)

        assert exc_info.value.actual == 149
    else:
        assert prepare_summary_text(text, minimum=150, maximum=8000) == text.strip()


@pytest.mark.parametrize("whitespace", ["\t", "\n", "\u00a0", "\u202f", "\u3000"])
def test_prepare_summary_text_excludes_unicode_whitespace_from_actual(whitespace):
    text = ("가" + whitespace) * 149

    with pytest.raises(SummaryInputTooShort) as exc_info:
        prepare_summary_text(text, minimum=150, maximum=8000)

    assert exc_info.value.actual == 149


def test_prepare_summary_text_checks_minimum_after_maximum_truncation():
    text = "가" + (" " * 7999) + ("나" * 149)

    with pytest.raises(SummaryInputTooShort) as exc_info:
        prepare_summary_text(text, minimum=150, maximum=8000)

    assert exc_info.value.actual == 1
    assert exc_info.value.minimum == 150


def test_prompt_core_has_no_transport_fields():
    prompt = build_summary_prompt("원문")

    assert prompt.endswith("원문")
    assert "requestId" not in prompt
    assert "taskId" not in prompt
