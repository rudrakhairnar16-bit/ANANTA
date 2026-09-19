import argparse
import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agents.base_agent import get_agent

ROOT = pathlib.Path(__file__).resolve().parents[1]

STAGES = [
    "story", "screenplay", "scene_plan", "character", "world",
    "storyboard", "director", "camera", "visual", "motion",
    "voice", "music", "bgm", "sfx", "lipsync",
    "edit", "adobe_export", "qa", "export"
]

def run(brief_path: str):
    print(f"\n{'='*60}")
    print("ANANTA Multi-Agent Production Engine")
    print(f"{'='*60}\n")

    brief = json.loads(pathlib.Path(brief_path).read_text(encoding="utf-8"))
    brief["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    brief["status"] = "in_progress"
    brief["version"] = 0

    episode_id = brief.get("episode_id", "UNKNOWN")
    print(f"Episode: {episode_id} - {brief.get('title', 'Untitled')}")
    print(f"Logline: {brief.get('logline', 'N/A')}")
    print(f"Duration: {brief.get('duration_seconds', 0)} seconds")
    print(f"Characters: {len(brief.get('characters', []))}")
    print(f"Locations: {len(brief.get('locations', []))}")
    print(f"Scenes: {len(brief.get('scenes', []))}")
    print(f"\nStages to execute: {len(STAGES)}")
    print(f"{'-'*60}\n")

    current_data = brief
    completed_stages = []
    failed_stages = []

    for i, stage in enumerate(STAGES, 1):
        print(f"[{i}/{len(STAGES)}] Running {stage.upper()} Agent...")

        try:
            agent = get_agent(stage)
            current_data = agent.run(current_data)
            completed_stages.append(stage)
            print(f"  [OK] {stage} completed\n")
        except Exception as e:
            print(f"  [FAIL] {stage} failed: {e}\n")
            failed_stages.append({"stage": stage, "error": str(e)})
            current_data["stage"] = stage
            current_data["error"] = str(e)
            current_data["status"] = "failed"
            break

    current_data["status"] = "completed" if not failed_stages else "failed"
    current_data["completed_stages"] = completed_stages
    current_data["failed_stages"] = failed_stages
    current_data["total_stages"] = len(STAGES)
    current_data["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    summary = {
        "episode_id": episode_id,
        "title": brief.get("title"),
        "stages_total": len(STAGES),
        "stages_completed": len(completed_stages),
        "stages_failed": len(failed_stages),
        "status": current_data["status"],
        "completed_stages": completed_stages,
        "failed_stages": failed_stages
    }

    print(f"{'='*60}")
    print("PIPELINE SUMMARY")
    print(f"{'='*60}")
    print(json.dumps(summary, indent=2))

    summary_file = ROOT / "outputs" / f"{episode_id}_pipeline_summary.json"
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSummary written to: {summary_file}")

    return current_data

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ANANTA Multi-Agent Production Pipeline")
    ap.add_argument("--brief", required=True, help="Path to episode brief JSON")
    args = ap.parse_args()

    try:
        run(args.brief)
    except KeyboardInterrupt:
        print("\n\nPipeline interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nPipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
