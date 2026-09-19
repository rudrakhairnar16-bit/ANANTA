import pytest

from pipeline.dependencies import (
    DependencyGraph,
    StageSpec,
    get_default_dependency_graph,
    get_stage_specs,
)


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
