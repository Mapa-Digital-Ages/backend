"""Unit tests for pure trail transition logic."""

from md_backend.models.db_models import RuleTypeEnum
from md_backend.services.trail.transition_engine import TransitionRule, pick_next_sub_path


def _rule(
    rule_type: RuleTypeEnum,
    destination_id: int | None,
    rule_value: int | None = None,
) -> TransitionRule:
    return TransitionRule(
        rule_type=rule_type,
        rule_value=rule_value,
        destination_id=destination_id,
    )


def test_bigger_than_rule_picks_destination():
    """BIGGER_THAN rules return their destination when the score is higher."""
    rules = [_rule(RuleTypeEnum.BIGGER_THAN, 20, rule_value=2)]

    assert pick_next_sub_path(rules, score=3, fallback_next_id=99) == 20


def test_smaller_than_rule_picks_destination():
    """SMALLER_THAN rules return their destination when the score is lower."""
    rules = [_rule(RuleTypeEnum.SMALLER_THAN, 30, rule_value=2)]

    assert pick_next_sub_path(rules, score=1, fallback_next_id=99) == 30


def test_standard_used_when_no_conditional_matches():
    """STANDARD is used when no conditional rule matches."""
    rules = [
        _rule(RuleTypeEnum.BIGGER_THAN, 20, rule_value=5),
        _rule(RuleTypeEnum.STANDARD, 40),
    ]

    assert pick_next_sub_path(rules, score=1, fallback_next_id=99) == 40


def test_falls_back_to_next_by_order_when_no_transitions():
    """Ordered fallback is used when no explicit transition exists."""
    assert pick_next_sub_path([], score=None, fallback_next_id=7) == 7


def test_returns_none_on_last_sub_path():
    """No transition and no fallback means the trail is completed."""
    assert pick_next_sub_path([], score=None, fallback_next_id=None) is None
