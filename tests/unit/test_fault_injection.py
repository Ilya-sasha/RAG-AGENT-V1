import pytest

from agent_runtime.testing.faults import (
    FaultPoint,
    FaultRule,
    NoopFaultInjector,
    RuleBasedFaultInjector,
)


def test_noop_fault_injector_never_raises() -> None:
    injector = NoopFaultInjector()
    injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")


def test_rule_based_fault_injector_raises_on_matching_count() -> None:
    injector = RuleBasedFaultInjector(
        [
            FaultRule(
                point=FaultPoint.MODEL_BEFORE_COMPLETE,
                times=2,
                exception_factory=lambda: RuntimeError("injected model failure"),
            )
        ]
    )

    injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")

    with pytest.raises(RuntimeError, match="injected model failure"):
        injector.trigger(FaultPoint.MODEL_BEFORE_COMPLETE, run_id="run-1")


def test_rule_based_fault_injector_does_not_raise_after_count_passes() -> None:
    injector = RuleBasedFaultInjector(
        [
            FaultRule(
                point=FaultPoint.TOOL_BEFORE_EXECUTE,
                times=1,
                exception_factory=lambda: RuntimeError("injected tool failure"),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="injected tool failure"):
        injector.trigger(FaultPoint.TOOL_BEFORE_EXECUTE, tool_name="payment-api")

    injector.trigger(FaultPoint.TOOL_BEFORE_EXECUTE, tool_name="payment-api")
