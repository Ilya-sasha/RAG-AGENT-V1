from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class FaultPoint(StrEnum):
    RUN_CREATE_BEFORE_DISPATCH = "run_create_before_dispatch"
    RUN_RESUME_BEFORE_EXECUTE = "run_resume_before_execute"
    MODEL_BEFORE_COMPLETE = "model_before_complete"
    TOOL_BEFORE_EXECUTE = "tool_before_execute"
    TOOL_BEFORE_RESUME = "tool_before_resume"


@dataclass(frozen=True, slots=True)
class FaultRule:
    point: FaultPoint
    times: int
    exception_factory: Callable[[], Exception]


class FaultInjector(Protocol):
    def trigger(self, point: FaultPoint, **context: Any) -> None: ...


class NoopFaultInjector:
    def trigger(self, point: FaultPoint, **context: Any) -> None:
        del point, context


class RuleBasedFaultInjector:
    def __init__(self, rules: Sequence[FaultRule]) -> None:
        self._rules = list(rules)
        self._counts: dict[FaultPoint, int] = defaultdict(int)
        self._fired_rule_indexes: set[int] = set()

    def trigger(self, point: FaultPoint, **context: Any) -> None:
        del context
        self._counts[point] += 1
        count = self._counts[point]
        for index, rule in enumerate(self._rules):
            if index in self._fired_rule_indexes:
                continue
            if rule.point == point and rule.times == count:
                self._fired_rule_indexes.add(index)
                raise rule.exception_factory()
