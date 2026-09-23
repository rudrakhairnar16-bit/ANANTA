import os
import pathlib
import subprocess
import sys

import pytest

from pipeline.dependencies import (
    DependencyGraph,
    StageSpec,
    get_default_dependency_graph,
    get_stage_specs,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_stage_spec_creation():
    spec = StageSpec(name="story", dependencies=[], required_inputs=["episode_id", "title"])
    assert spec.name == "story"
    assert spec.dependencies == []
    assert spec.required_inputs == ["episode_id", "title"]
    assert spec.optional is False


def test_dependency_graph_creation():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["b"]),
    ]
    graph = DependencyGraph(stages)
    assert len(graph.stages) == 3


def test_dependency_graph_get_dependencies():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["b"]),
    ]
    graph = DependencyGraph(stages)
    assert graph.get_dependencies("c") == ["b"]
    assert graph.get_dependencies("a") == []


def test_dependency_graph_get_dependents():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["b"]),
    ]
    graph = DependencyGraph(stages)
    assert graph.get_dependents("a") == ["b"]
    assert graph.get_dependents("b") == ["c"]
    assert graph.get_dependents("c") == []


def test_dependency_graph_execution_order():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["b"]),
    ]
    graph = DependencyGraph(stages)
    order = graph.get_execution_order()
    assert order == ["a", "b", "c"]


def test_dependency_graph_execution_order_complex():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["a"]),
        StageSpec(name="d", dependencies=["b", "c"]),
    ]
    graph = DependencyGraph(stages)
    order = graph.get_execution_order()
    assert order[0] == "a"
    assert order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")
    assert order[-1] == "d"


def test_dependency_graph_cycle_detection():
    stages = [
        StageSpec(name="a", dependencies=["b"]),
        StageSpec(name="b", dependencies=["a"]),
    ]
    graph = DependencyGraph(stages)
    with pytest.raises(ValueError, match="Cycle detected"):
        graph.get_execution_order()


def test_dependency_graph_parallel_groups():
    stages = [
        StageSpec(name="a", dependencies=[]),
        StageSpec(name="b", dependencies=["a"], parallel_group="group1"),
        StageSpec(name="c", dependencies=["a"], parallel_group="group1"),
        StageSpec(name="d", dependencies=["b", "c"]),
    ]
    graph = DependencyGraph(stages)
    groups = graph.get_parallel_groups()
    assert len(groups) >= 1


def test_dependency_graph_validate():
    stages = [
        StageSpec(name="a", dependencies=["unknown"]),
    ]
    graph = DependencyGraph(stages)
    errors = graph.validate()
    assert len(errors) == 1
    assert "unknown" in errors[0]


def test_default_stage_specs():
    specs = get_stage_specs()
    assert len(specs) == 19
    names = [s.name for s in specs]
    assert "story" in names
    assert "screenplay" in names
    assert "export" in names


def test_default_dependency_graph():
    graph = get_default_dependency_graph()
    assert len(graph.stages) == 19
    order = graph.get_execution_order()
    assert order[0] == "story"
    assert "screenplay" in order
    assert "export" in order


def test_story_dependencies():
    graph = get_default_dependency_graph()
    deps = graph.get_dependencies("story")
    assert deps == []


def test_screenplay_dependencies():
    graph = get_default_dependency_graph()
    deps = graph.get_dependencies("screenplay")
    assert "story" in deps


def test_export_dependencies():
    graph = get_default_dependency_graph()
    deps = graph.get_dependencies("export")
    assert "qa" in deps


def test_character_dependencies():
    graph = get_default_dependency_graph()
    deps = graph.get_dependencies("character")
    assert "story" in deps


def test_qa_dependencies():
    graph = get_default_dependency_graph()
    deps = graph.get_dependencies("qa")
    assert "adobe_export" in deps
    assert "lipsync" in deps
    assert "sfx" in deps
    assert "bgm" in deps


def test_execution_order_deterministic_across_repeated_calls():
    graph = get_default_dependency_graph()
    first = graph.get_execution_order()
    for _ in range(20):
        assert graph.get_execution_order() == first


def test_execution_order_deterministic_across_hash_seeds():
    script = (
        "import json;"
        "from pipeline.dependencies import get_default_dependency_graph;"
        "print(json.dumps(get_default_dependency_graph().get_execution_order()))"
    )
    orders = set()
    for seed in ("0", "1", "424242"):
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        )
        orders.add(result.stdout.strip())
    assert len(orders) == 1


def _independent_execution_order(stages):
    adjacency = {s.name: set(s.dependencies) for s in stages}
    dependents = {name: set() for name in adjacency}
    for name, deps in adjacency.items():
        for dep in deps:
            dependents[dep].add(name)
    in_degree = {name: len(deps) for name, deps in adjacency.items()}
    ready = sorted(name for name, degree in in_degree.items() if degree == 0)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for dependent in sorted(dependents.get(node, set())):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)
                ready.sort()
    return order


def test_default_order_matches_independent_oracle():
    graph = get_default_dependency_graph()
    oracle = _independent_execution_order(graph.stages.values())
    assert graph.get_execution_order() == oracle


def test_execution_order_sorted_tiebreak_diamond():
    specs = [
        StageSpec(name="d", dependencies=["b", "c"]),
        StageSpec(name="b", dependencies=["a"]),
        StageSpec(name="c", dependencies=["a"]),
        StageSpec(name="a", dependencies=[]),
    ]
    graph = DependencyGraph(specs)
    assert graph.get_execution_order() == ["a", "b", "c", "d"]


def test_get_dependencies_sorted():
    graph = get_default_dependency_graph()
    for stage in graph.stages:
        assert graph.get_dependencies(stage) == sorted(graph.get_dependencies(stage))
    assert graph.get_dependencies("qa") == ["adobe_export", "bgm", "lipsync", "sfx"]


def test_get_dependents_sorted():
    graph = get_default_dependency_graph()
    for stage in graph.stages:
        assert graph.get_dependents(stage) == sorted(graph.get_dependents(stage))
    assert graph.get_dependents("screenplay") == sorted(
        ["scene_plan", "storyboard", "bgm", "sfx"]
    )
