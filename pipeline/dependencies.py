from collections import defaultdict
from dataclasses import dataclass, field
from heapq import heapify, heappop, heappush


@dataclass
class StageSpec:
    name: str
    dependencies: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    produces_outputs: list[str] = field(default_factory=list)
    optional: bool = False
    parallel_group: str | None = None


class DependencyGraph:
    def __init__(self, stages: list[StageSpec] | None = None):
        self.stages: dict[str, StageSpec] = {}
        self._adjacency: dict[str, set[str]] = defaultdict(set)
        self._reverse_adjacency: dict[str, set[str]] = defaultdict(set)

        if stages:
            for spec in stages:
                self.add_stage(spec)

    def add_stage(self, spec: StageSpec):
        self.stages[spec.name] = spec
        for dep in spec.dependencies:
            self._adjacency[dep].add(spec.name)
            self._reverse_adjacency[spec.name].add(dep)

    def get_dependencies(self, stage: str) -> list[str]:
        return sorted(self._reverse_adjacency.get(stage, set()))

    def get_dependents(self, stage: str) -> list[str]:
        return sorted(self._adjacency.get(stage, set()))

    def get_execution_order(self) -> list[str]:
        in_degree = {
            name: len(self._reverse_adjacency.get(name, set())) for name in self.stages
        }
        queue = [name for name, degree in in_degree.items() if degree == 0]
        heapify(queue)
        order = []

        while queue:
            node = heappop(queue)
            order.append(node)
            for dependent in sorted(self._adjacency.get(node, set())):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    heappush(queue, dependent)

        if len(order) != len(self.stages):
            raise ValueError("Cycle detected in dependency graph")

        return order

    def get_parallel_groups(self) -> list[list[str]]:
        order = self.get_execution_order()
        groups: list[list[str]] = []
        current_group: list[str] = []

        for stage_name in order:
            spec = self.stages[stage_name]
            deps = set(self.get_dependencies(stage_name))

            if not current_group or spec.parallel_group and all(d in current_group for d in deps):
                current_group.append(stage_name)
            else:
                groups.append(current_group)
                current_group = [stage_name]

        if current_group:
            groups.append(current_group)

        return groups

    def validate(self) -> list[str]:
        errors = []
        for spec in self.stages.values():
            for dep in spec.dependencies:
                if dep not in self.stages:
                    errors.append(f"Stage '{spec.name}' depends on unknown stage '{dep}'")
        return errors


DEFAULT_STAGE_SPECS = [
    StageSpec(
        name="story",
        dependencies=[],
        required_inputs=["episode_id", "title"],
        produces_outputs=["synopsis", "themes", "acts", "beats"],
    ),
    StageSpec(
        name="screenplay",
        dependencies=["story"],
        required_inputs=["synopsis"],
        produces_outputs=["scenes", "total_pages"],
    ),
    StageSpec(
        name="scene_plan",
        dependencies=["screenplay"],
        required_inputs=["scenes"],
        produces_outputs=["breakdown"],
    ),
    StageSpec(
        name="character",
        dependencies=["story"],
        required_inputs=["characters"],
        produces_outputs=["profiles"],
    ),
    StageSpec(
        name="world",
        dependencies=["story"],
        required_inputs=["locations"],
        produces_outputs=["rules", "technology", "society"],
    ),
    StageSpec(
        name="storyboard",
        dependencies=["screenplay", "scene_plan"],
        required_inputs=["scenes", "breakdown"],
        produces_outputs=["panels", "key_frames"],
    ),
    StageSpec(
        name="director",
        dependencies=["storyboard"],
        required_inputs=["panels", "key_frames"],
        produces_outputs=["vision", "shot_style", "pacing"],
    ),
    StageSpec(
        name="camera",
        dependencies=["director"],
        required_inputs=["vision", "shot_style"],
        produces_outputs=["lenses", "movement", "lighting"],
    ),
    StageSpec(
        name="visual",
        dependencies=["director", "camera"],
        required_inputs=["vision", "lenses"],
        produces_outputs=["concept_art", "vfx_breakdown", "color_palette"],
    ),
    StageSpec(
        name="motion",
        dependencies=["visual"],
        required_inputs=["concept_art", "vfx_breakdown"],
        produces_outputs=["animation_style", "key_sequences"],
    ),
    StageSpec(
        name="voice",
        dependencies=["character"],
        required_inputs=["characters", "profiles"],
        produces_outputs=["casting", "direction", "recording_notes"],
    ),
    StageSpec(
        name="music",
        dependencies=["story"],
        required_inputs=["themes", "synopsis"],
        produces_outputs=["themes", "cues", "instrumentation"],
    ),
    StageSpec(
        name="bgm",
        dependencies=["music", "screenplay"],
        required_inputs=["themes", "scenes"],
        produces_outputs=["tracks", "ducking_points", "transitions"],
    ),
    StageSpec(
        name="sfx",
        dependencies=["screenplay", "scene_plan"],
        required_inputs=["scenes", "breakdown"],
        produces_outputs=["design", "spot_effects", "ambience"],
    ),
    StageSpec(
        name="lipsync",
        dependencies=["voice"],
        required_inputs=["characters", "casting"],
        produces_outputs=["phoneme_maps", "viseme_schedule"],
    ),
    StageSpec(
        name="edit",
        dependencies=["visual", "motion", "camera"],
        required_inputs=["concept_art", "animation_style", "lenses"],
        produces_outputs=["assembly", "pacing_notes", "transitions"],
    ),
    StageSpec(
        name="adobe_export",
        dependencies=["edit"],
        required_inputs=["assembly", "transitions"],
        produces_outputs=["timeline_xml", "markers_csv"],
    ),
    StageSpec(
        name="qa",
        dependencies=["adobe_export", "lipsync", "sfx", "bgm"],
        required_inputs=["all"],
        produces_outputs=["checks_passed", "issues", "approval"],
    ),
    StageSpec(
        name="export",
        dependencies=["qa"],
        required_inputs=["approval"],
        produces_outputs=["deliverables", "specs", "package"],
    ),
]


def get_default_dependency_graph() -> DependencyGraph:
    return DependencyGraph(DEFAULT_STAGE_SPECS)


def get_stage_specs() -> list[StageSpec]:
    return DEFAULT_STAGE_SPECS
