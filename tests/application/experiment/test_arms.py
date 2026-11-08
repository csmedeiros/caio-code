"""Offline tests for the experiment arm catalogue."""

from __future__ import annotations

import pytest

from caio_code.application.experiment.arms import default_arms, select_arms
from caio_code.config import Settings, WindowConfig

EXPECTED_ARMS = (
    "baseline_full_history",
    "baseline_capped",
    "sliding_window",
    "message_selection",
    "message_selection_decision",
    "message_selection_decision_plus_truncation",
    "anchored_compaction",
    "tool_truncation_only",
    "sliding_window_plus_truncation",
    "message_selection_plus_truncation",
    "anchored_compaction_plus_truncation",
)


def _settings(window_tokens: int = 8_000) -> Settings:
    return Settings(window=WindowConfig(tokens=window_tokens))


def test_default_arms_returns_the_eleven_documented_arms_in_order() -> None:
    arms = default_arms(_settings())

    assert tuple(arm.name for arm in arms) == EXPECTED_ARMS


def test_the_decision_arms_are_the_only_ones_scored_by_the_decision_model() -> None:
    arms = {arm.name: arm for arm in default_arms(_settings())}

    decision = sorted(name for name, arm in arms.items() if arm.scorer_kind == "decision")
    assert decision == [
        "message_selection_decision",
        "message_selection_decision_plus_truncation",
    ]
    for name in decision:
        assert arms[name].needs_scores, name
    for name, arm in arms.items():
        if not arm.needs_scores:
            assert arm.scorer_kind == "lexical", name


def test_every_arm_pipeline_ends_with_the_structure_repair_policy() -> None:
    settings = _settings()

    for arm in default_arms(settings):
        pipeline = arm.pipeline(settings)
        assert pipeline.policies[-1] == "structure_repair", arm.name


def test_select_arms_filters_by_name() -> None:
    arms = select_arms(_settings(), ["sliding_window", "baseline_capped"])

    assert tuple(arm.name for arm in arms) == ("baseline_capped", "sliding_window")


def test_select_arms_without_names_returns_everything() -> None:
    assert len(select_arms(_settings(), None)) == len(EXPECTED_ARMS)


def test_select_arms_raises_value_error_listing_the_available_arms() -> None:
    with pytest.raises(ValueError, match="unknown arms: nope") as excinfo:
        select_arms(_settings(), ["nope"])

    for name in EXPECTED_ARMS:
        assert name in str(excinfo.value)


def test_every_arm_window_matches_the_configured_window() -> None:
    settings = _settings(window_tokens=1_234)

    assert all(arm.window_tokens == 1_234 for arm in default_arms(settings))


def test_truncation_arms_carry_two_or_three_pipeline_steps() -> None:
    settings = _settings()

    alone = select_arms(settings, ["tool_truncation_only"])[0]
    combined = select_arms(settings, ["anchored_compaction_plus_truncation"])[0]

    assert len(alone.pipeline(settings).policies) == 2
    assert len(combined.pipeline(settings).policies) == 3


def test_compaction_arms_flag_needs_compaction() -> None:
    arms = {arm.name: arm for arm in default_arms(_settings())}

    assert arms["anchored_compaction"].needs_compaction
    assert arms["anchored_compaction_plus_truncation"].needs_compaction
    assert not arms["sliding_window"].needs_compaction


def test_selection_arms_flag_needs_scores() -> None:
    arms = {arm.name: arm for arm in default_arms(_settings())}

    assert arms["message_selection"].needs_scores
    assert arms["message_selection_plus_truncation"].needs_scores
    assert not arms["sliding_window"].needs_scores


def test_only_baseline_capped_enforces_the_window() -> None:
    arms = {arm.name: arm for arm in default_arms(_settings())}

    assert arms["baseline_capped"].enforce_window
    assert not arms["baseline_full_history"].enforce_window
