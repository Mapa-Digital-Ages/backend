"""Pure adaptive transition logic for trails."""

from dataclasses import dataclass

from md_backend.models.db_models import RuleTypeEnum


@dataclass(frozen=True)
class TransitionRule:
    """A transition rule detached from persistence concerns."""

    rule_type: RuleTypeEnum
    rule_value: int | None
    destination_id: int | None


def pick_next_sub_path(
    transitions: list[TransitionRule],
    score: int | None,
    fallback_next_id: int | None,
) -> int | None:
    """Return first matching conditional, then standard, then ordered fallback."""
    standard_dest: int | None = None
    for transition in transitions:
        if transition.rule_type == RuleTypeEnum.STANDARD:
            if standard_dest is None:
                standard_dest = transition.destination_id
            continue
        if score is None or transition.rule_value is None:
            continue
        if (
            transition.rule_type == RuleTypeEnum.BIGGER_THAN
            and score > transition.rule_value
        ):
            return transition.destination_id
        if (
            transition.rule_type == RuleTypeEnum.SMALLER_THAN
            and score < transition.rule_value
        ):
            return transition.destination_id
    return standard_dest if standard_dest is not None else fallback_next_id
