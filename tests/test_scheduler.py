import pytest

from pipeline.dependencies import get_default_dependency_graph
from pipeline.scheduler import SchedulerError, StageScheduler, create_ananta_scheduler
from pipeline.state import InvalidStateTransitionError, StageStatus


def _simulate(scheduler: StageScheduler) -> tuple[str, ...]:
    order = []
    while not scheduler.is_finished():
        ready = scheduler.ready_stages()
        assert ready, "scheduler deadlocked: no ready stage but execution not finished"
        for stage in ready:
            scheduler.mark_queued(stage)
            scheduler.mark_running(stage)
            scheduler.complete(stage)
            order.append(stage)
    return tuple(order)


# --- A. LINEAR DEPENDENCY CHAIN ---


def test_linear_chain_b_not_ready_before_a():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    assert scheduler.ready_stages() == ("A",)
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("B")
    assert scheduler.instance("B").status == StageStatus.PENDING


def test_linear_chain_b_ready_after_a_completes():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")

    assert scheduler.ready_stages() == ("B",)
    assert scheduler.instance("C").status == StageStatus.PENDING


def test_linear_chain_c_ready_only_after_b_completes():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    scheduler.mark_queued("B")
    scheduler.mark_running("B")
    scheduler.complete("B")

    assert scheduler.ready_stages() == ("C",)
    scheduler.mark_queued("C")
    scheduler.mark_running("C")
    scheduler.complete("C")
    assert scheduler.is_finished()
    assert scheduler.completed_stages() == ("A", "B", "C")


# --- B. DIAMOND DEPENDENCY GRAPH ---


def _diamond() -> StageScheduler:
    return StageScheduler(
        ("A", "B", "C", "D"),
        {"B": ("A",), "C": ("A",), "D": ("B", "C")},
    )


def test_diamond_after_a_both_branch_nodes_ready():
    scheduler = _diamond()
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    assert scheduler.ready_stages() == ("B", "C")


def test_diamond_d_waits_for_both_branches():
    scheduler = _diamond()
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")

    scheduler.mark_queued("B")
    scheduler.mark_running("B")
    scheduler.complete("B")
    assert scheduler.instance("D").status == StageStatus.PENDING
    assert scheduler.ready_stages() == ("C",)
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("D")

    scheduler.mark_queued("C")
    scheduler.mark_running("C")
    scheduler.complete("C")
    assert scheduler.ready_stages() == ("D",)


def test_diamond_ready_ordering_stable_across_runs():
    for _ in range(3):
        scheduler = _diamond()
        scheduler.mark_queued("A")
        scheduler.mark_running("A")
        scheduler.complete("A")
        assert scheduler.ready_stages() == ("B", "C")


# --- C. INDEPENDENT BRANCHES ---


def test_independent_branches_both_ready_with_deterministic_order():
    scheduler = StageScheduler(("A", "B", "C", "D"), {"B": ("A",), "D": ("C",)})
    assert scheduler.ready_stages() == ("A", "C")
    for _ in range(3):
        fresh = StageScheduler(("A", "B", "C", "D"), {"B": ("A",), "D": ("C",)})
        assert fresh.ready_stages() == ("A", "C")


def test_independent_branches_run_to_completion():
    scheduler = StageScheduler(("A", "B", "C", "D"), {"B": ("A",), "D": ("C",)})
    order = _simulate(scheduler)
    assert order == ("A", "C", "B", "D")


# --- D. FAILURE ISOLATION ---


def test_failure_isolates_downstream_via_blocked():
    scheduler = StageScheduler(("A", "B", "C", "D"), {"B": ("A",), "D": ("C",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.fail("A", "boom")

    assert scheduler.failed_stages() == ("A",)
    assert scheduler.instance("B").status == StageStatus.BLOCKED
    assert scheduler.ready_stages() == ("C",)

    scheduler.mark_queued("C")
    scheduler.mark_running("C")
    scheduler.complete("C")
    assert scheduler.ready_stages() == ("D",)

    scheduler.mark_queued("D")
    scheduler.mark_running("D")
    scheduler.complete("D")
    assert scheduler.is_finished()
    assert scheduler.blocked_stages() == ("B",)
    assert scheduler.instance("B").status == StageStatus.BLOCKED


# --- E. CANCELLATION SEMANTICS ---


def test_cancel_queued_stage_blocks_downstream():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    scheduler.mark_queued("B")
    scheduler.cancel("B")

    assert scheduler.instance("B").status == StageStatus.CANCELLED
    assert scheduler.instance("C").status == StageStatus.BLOCKED
    assert scheduler.cancelled_stages() == ("B",)
    assert scheduler.blocked_stages() == ("C",)


def test_cancel_pending_stage_blocks_downstream():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.cancel("A")
    assert scheduler.instance("A").status == StageStatus.CANCELLED
    assert scheduler.instance("B").status == StageStatus.BLOCKED
    assert scheduler.is_finished()


def test_cancel_running_stage_representation():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.cancel("A")
    assert scheduler.instance("A").status == StageStatus.CANCELLED
    assert scheduler.instance("B").status == StageStatus.BLOCKED


# --- F. DUPLICATE PREVENTION ---


def test_duplicate_admission_rejected():
    scheduler = StageScheduler(("A",), {})
    scheduler.mark_queued("A")
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("A")


def test_duplicate_completion_rejected():
    scheduler = StageScheduler(("A",), {})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    with pytest.raises(InvalidStateTransitionError):
        scheduler.complete("A")


def test_duplicate_running_rejected():
    scheduler = StageScheduler(("A",), {})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    with pytest.raises(InvalidStateTransitionError):
        scheduler.mark_running("A")


def test_no_stage_ready_and_terminal_simultaneously():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    assert "A" not in scheduler.ready_stages()
    assert scheduler.completed_stages() == ("A",)


# --- SKIPPED DEPENDENCY POLICY ---


def test_skipped_dependency_blocks_downstream():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    scheduler.skip("A")
    assert scheduler.instance("A").status == StageStatus.SKIPPED
    assert scheduler.instance("B").status == StageStatus.BLOCKED
    assert scheduler.instance("C").status == StageStatus.BLOCKED
    assert scheduler.skipped_stages() == ("A",)
    assert scheduler.blocked_stages() == ("B", "C")


def test_skipped_does_not_satisfy_required_dependency():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.skip("A")
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("B")


def test_skipped_is_terminal_and_not_re_queued():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.skip("A")
    with pytest.raises(InvalidStateTransitionError):
        scheduler.complete("A")
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("A")


def test_optional_dependency_does_not_block():
    scheduler = StageScheduler(
        ("A", "B"),
        {"B": ("A",)},
        optional_dependencies={"B": ("A",)},
    )
    scheduler.skip("A")
    assert scheduler.instance("B").status == StageStatus.PENDING
    assert scheduler.ready_stages() == ("B",)
    scheduler.mark_queued("B")
    scheduler.mark_running("B")
    scheduler.complete("B")
    assert scheduler.instance("B").status == StageStatus.COMPLETED


# --- BLOCKED DOWNSTREAM REPORTING ---


def test_blocked_downstream_reporting():
    scheduler = StageScheduler(("A", "B", "C"), {"B": ("A",), "C": ("B",)})
    scheduler.skip("A")
    assert scheduler.blocked_downstream("A") == ("B", "C")
    assert scheduler.blocked_downstream("B") == ("C",)


# --- G. DETERMINISM ---


def test_diamond_deterministic_repeat():
    def scenario():
        scheduler = _diamond()
        events = []
        scheduler.mark_queued("A")
        scheduler.mark_running("A")
        scheduler.complete("A")
        events.append(scheduler.ready_stages())
        scheduler.mark_queued("B")
        scheduler.mark_running("B")
        scheduler.complete("B")
        events.append(scheduler.ready_stages())
        scheduler.mark_queued("C")
        scheduler.mark_running("C")
        scheduler.complete("C")
        events.append(scheduler.ready_stages())
        return tuple(events), scheduler.completed_stages()

    expected = scenario()
    for _ in range(3):
        assert scenario() == expected


# --- SCHEduLER IMMUTABILITY / OBSERVABILITY ---


def test_instances_are_immutable_values():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    inst = scheduler.instance("A")
    with pytest.raises(AttributeError):
        inst.status = StageStatus.COMPLETED


def test_snapshot_is_frozen_and_structured():
    scheduler = StageScheduler(("A", "B"), {"B": ("A",)})
    scheduler.mark_queued("A")
    scheduler.mark_running("A")
    scheduler.complete("A")
    snap = scheduler.snapshot()
    assert snap.completed == ("A",)
    assert snap.ready == ("B",)
    assert snap.finished is False
    with pytest.raises(AttributeError):
        snap.completed = ("X",)


def test_unknown_stage_raises_scheduler_error():
    scheduler = StageScheduler(("A",), {})
    with pytest.raises(SchedulerError):
        scheduler.mark_queued("NOPE")
    with pytest.raises(SchedulerError):
        scheduler.instance("NOPE")


def test_duplicate_stages_rejected_at_construction():
    with pytest.raises(SchedulerError):
        StageScheduler(("A", "A"), {})


def test_unknown_dependency_rejected_at_construction():
    with pytest.raises(SchedulerError):
        StageScheduler(("A",), {"A": ("missing",)})


# --- H. FULL 19-STAGE GRAPH ---


def test_nineteen_stage_graph_registration_matches_m1():
    scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
    graph = get_default_dependency_graph()
    assert scheduler.stage_order() == tuple(graph.get_execution_order())
    assert len(scheduler.stage_order()) == 19
    assert scheduler.required_dependencies("bgm") == ("music", "screenplay")
    assert scheduler.required_dependencies("qa") == (
        "adobe_export",
        "bgm",
        "lipsync",
        "sfx",
    )
    assert len(scheduler.instances()) == 19
    assert all(i.status == StageStatus.PENDING for i in scheduler.instances())


def test_nineteen_stage_graph_schedulable_in_deterministic_order():
    scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
    assert scheduler.ready_stages() == ("story",)
    order = _simulate(scheduler)
    assert len(order) == 19
    assert len(set(order)) == 19
    assert order[0] == "story"
    assert order[-1] == "export"
    for index, stage in enumerate(order):
        for dep in scheduler.required_dependencies(stage):
            assert dep in order[:index], f"{stage} ran before dependency {dep}"
    assert scheduler.is_finished()
    assert scheduler.completed_stages() == tuple(scheduler.stage_order())
    assert scheduler.failed_stages() == ()
    assert scheduler.blocked_stages() == ()


def test_nineteen_stage_graph_deterministic_simulation():
    first = _simulate(create_ananta_scheduler(episode_id="ANANTA-S01E01"))
    second = _simulate(create_ananta_scheduler(episode_id="ANANTA-S01E01"))
    assert first == second
    assert len(first) == 19
    assert len(set(first)) == 19
    assert first == (
        "story",
        "character",
        "music",
        "screenplay",
        "world",
        "bgm",
        "scene_plan",
        "voice",
        "sfx",
        "storyboard",
        "lipsync",
        "director",
        "camera",
        "visual",
        "motion",
        "edit",
        "adobe_export",
        "qa",
        "export",
    )


def test_nineteen_stage_graph_no_deadlock():
    scheduler = create_ananta_scheduler(episode_id="ANANTA-S01E01")
    guard = 0
    while not scheduler.is_finished():
        ready = scheduler.ready_stages()
        assert ready
        for stage in ready:
            scheduler.mark_queued(stage)
            scheduler.mark_running(stage)
            scheduler.complete(stage)
        guard += 1
        assert guard < 100
