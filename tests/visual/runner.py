"""Runner and report generator for Metaglyph visual test scenarios."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from .diff import DiffResult, VisualDiff
    from .harness import VisualHarness, VisualSnapshot
    from .scenarios import PREDEFINED_SCENARIOS, VisualScenario
except (ImportError, ValueError):
    # Running directly as a script
    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    if str(repo_root / "src") not in sys.path:
        sys.path.insert(0, str(repo_root / "src"))
    from tests.visual.diff import DiffResult, VisualDiff
    from tests.visual.harness import VisualHarness, VisualSnapshot
    from tests.visual.scenarios import PREDEFINED_SCENARIOS, VisualScenario

logger = logging.getLogger("metaglyph.visual.runner")


@dataclass
class ScenarioReport:
    """Individual scenario execution result and visual metrics."""

    scenario_name: str
    description: str
    viewport_size: list[int]
    image_path: str
    duration_ms: float
    status: str  # "PASSED", "FAILED", "DIFF_MISMATCH"
    error_message: str | None = None
    diff_result: dict | None = None


class ScenarioRunner:
    """Orchestrates visual scenario execution, diffing, and report creation."""

    def __init__(
        self,
        output_dir: str | Path,
        baseline_dir: str | Path | None = None,
        max_mismatch_pct: float = 0.05,
        viewport_size: tuple[int, int] = (1280, 820),
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.baseline_dir = Path(baseline_dir) if baseline_dir else None
        self.diff_engine = VisualDiff(max_mismatch_percentage=max_mismatch_pct)
        self.default_viewport = viewport_size

    async def run_scenario(
        self,
        scenario: VisualScenario,
        harness: VisualHarness,
    ) -> ScenarioReport:
        """Execute a single visual scenario within an initialized harness."""
        assert harness.driver is not None, "Driver not initialized"
        start_time = time.monotonic()

        harness.resize_viewport(scenario.viewport_size[0], scenario.viewport_size[1])
        error_msg: str | None = None
        status = "PASSED"
        diff_info: dict | None = None

        try:
            await scenario.execute(harness, harness.driver)
            snapshot = harness.capture_snapshot(scenario.name, scenario.description)

            # Baseline diffing if baseline directory is provided
            if self.baseline_dir:
                baseline_img = self.baseline_dir / f"{scenario.name}.png"
                if baseline_img.exists():
                    diff_img_path = self.output_dir / f"{scenario.name}_diff.png"
                    diff_res = self.diff_engine.compare_images(
                        baseline_path=baseline_img,
                        actual_path=snapshot.image_path,
                        diff_output_path=diff_img_path,
                    )
                    diff_info = asdict(diff_res)
                    if not diff_res.is_match:
                        status = "DIFF_MISMATCH"
                        error_msg = f"Visual mismatch: {diff_res.mismatch_percentage:.2f}% (max: {self.diff_engine.max_mismatch_percentage}%)"
                else:
                    logger.info("No baseline found for scenario '%s' at %s", scenario.name, baseline_img)

        except Exception as exc:
            status = "FAILED"
            error_msg = str(exc)
            logger.error("Scenario '%s' failed: %s", scenario.name, exc, exc_info=True)
            # Try capturing error state
            try:
                snapshot = harness.capture_snapshot(f"{scenario.name}_error", f"Error: {exc}")
            except Exception:
                snapshot = VisualSnapshot(
                    scenario_name=scenario.name,
                    image_path=self.output_dir / f"{scenario.name}.png",
                    viewport_size=scenario.viewport_size,
                    description=scenario.description,
                )

        duration = (time.monotonic() - start_time) * 1000.0

        return ScenarioReport(
            scenario_name=scenario.name,
            description=scenario.description,
            viewport_size=list(scenario.viewport_size),
            image_path=str(snapshot.image_path),
            duration_ms=round(duration, 2),
            status=status,
            error_message=error_msg,
            diff_result=diff_info,
        )

    async def run_all(
        self,
        scenarios: list[VisualScenario] | None = None,
    ) -> list[ScenarioReport]:
        """Execute multiple scenarios in a fresh isolated harness."""
        scenarios_to_run = scenarios or PREDEFINED_SCENARIOS
        reports: list[ScenarioReport] = []

        async with VisualHarness(output_dir=self.output_dir, viewport_size=self.default_viewport) as harness:
            for scenario in scenarios_to_run:
                report = await self.run_scenario(scenario, harness)
                reports.append(report)

        self.generate_markdown_gallery(reports)
        self.generate_html_gallery(reports)
        self.save_results_json(reports)

        return reports

    def save_results_json(self, reports: list[ScenarioReport]) -> Path:
        """Save structured JSON results."""
        out_json = self.output_dir / "results.json"
        data = {
            "timestamp": time.time(),
            "total": len(reports),
            "passed": sum(1 for r in reports if r.status == "PASSED"),
            "failed": sum(1 for r in reports if r.status == "FAILED"),
            "mismatches": sum(1 for r in reports if r.status == "DIFF_MISMATCH"),
            "reports": [asdict(r) for r in reports],
        }
        out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return out_json

    def generate_markdown_gallery(self, reports: list[ScenarioReport]) -> Path:
        """Generate GitHub-flavored Markdown visual test gallery."""
        md_lines = [
            "# Metaglyph Visual Test Gallery",
            "",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Scenarios:** {len(reports)} | **Passed:** {sum(1 for r in reports if r.status == 'PASSED')} | **Mismatches:** {sum(1 for r in reports if r.status == 'DIFF_MISMATCH')} | **Errors:** {sum(1 for r in reports if r.status == 'FAILED')}",
            "",
            "---",
            "",
        ]

        for report in reports:
            badge = "🟢 PASSED" if report.status == "PASSED" else ("🔴 FAILED" if report.status == "FAILED" else "🟡 DIFF MISMATCH")
            md_lines.extend([
                f"## `{report.scenario_name}` ({badge})",
                f"**Description:** {report.description}",
                f"**Viewport:** `{report.viewport_size[0]}x{report.viewport_size[1]}` | **Duration:** `{report.duration_ms}ms`",
                "",
            ])

            if report.error_message:
                md_lines.append(f"> [!WARNING]\n> {report.error_message}\n")

            md_lines.extend([
                f"![{report.scenario_name}]({report.image_path})",
                "",
                "---",
                "",
            ])

        gallery_path = self.output_dir / "gallery.md"
        gallery_path.write_text("\n".join(md_lines), encoding="utf-8")
        return gallery_path

    def generate_html_gallery(self, reports: list[ScenarioReport]) -> Path:
        """Generate self-contained HTML gallery for rich visual review."""
        items_html = []
        for r in reports:
            badge_color = "#10b981" if r.status == "PASSED" else ("#ef4444" if r.status == "FAILED" else "#f59e0b")
            img_rel = Path(r.image_path).name
            items_html.append(f"""
            <div class="card">
                <div class="header">
                    <h3><code>{r.scenario_name}</code></h3>
                    <span class="badge" style="background: {badge_color}22; color: {badge_color}; border: 1px solid {badge_color}66;">{r.status}</span>
                </div>
                <p class="desc">{r.description}</p>
                <p class="meta">Viewport: <b>{r.viewport_size[0]}x{r.viewport_size[1]}</b> | Duration: <b>{r.duration_ms}ms</b></p>
                <div class="img-wrapper">
                    <img src="{img_rel}" alt="{r.scenario_name}" loading="lazy" />
                </div>
            </div>
            """)

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Metaglyph Visual Test Gallery</title>
    <style>
        body {{
            background-color: #0f172a;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 32px;
        }}
        h1 {{ margin-top: 0; color: #38bdf8; font-size: 28px; }}
        .summary {{ margin-bottom: 24px; color: #94a3b8; font-size: 14px; }}
        .grid {{ display: flex; flex-direction: column; gap: 32px; }}
        .card {{
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
        }}
        .header {{ display: flex; justify-content: space-between; align-items: center; }}
        .header h3 {{ margin: 0; font-size: 18px; color: #f8fafc; }}
        .badge {{ padding: 4px 10px; border-radius: 6px; font-weight: bold; font-size: 12px; }}
        .desc {{ color: #cbd5e1; margin: 8px 0; font-size: 13px; }}
        .meta {{ color: #64748b; font-size: 12px; margin: 4px 0 16px 0; }}
        .img-wrapper {{
            background: #020617;
            border: 1px solid #1e293b;
            border-radius: 8px;
            overflow: hidden;
            text-align: center;
        }}
        img {{ max-width: 100%; height: auto; display: block; margin: 0 auto; }}
    </style>
</head>
<body>
    <h1>✦ Metaglyph Visual Test Gallery</h1>
    <div class="summary">
        Generated on {time.strftime('%Y-%m-%d %H:%M:%S')} &bull; {len(reports)} Scenarios
    </div>
    <div class="grid">
        {"".join(items_html)}
    </div>
</body>
</html>
"""
        html_path = self.output_dir / "gallery.html"
        html_path.write_text(html_content, encoding="utf-8")
        return html_path


def main() -> int:
    """CLI entry point for running visual scenarios."""
    parser = argparse.ArgumentParser(description="Metaglyph Visual Testing Scenario Runner")
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="/tmp/metaglyph_visual_reports",
        help="Directory to save generated screenshots and reports",
    )
    parser.add_argument(
        "--baseline",
        "-b",
        type=str,
        default=None,
        help="Directory containing baseline screenshots to compare against",
    )
    parser.add_argument(
        "--scenario",
        "-s",
        type=str,
        default=None,
        help="Specific scenario name to run (default: run all)",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="Maximum allowed mismatch percentage (default: 0.05%%)",
    )

    args = parser.parse_args()

    scenarios = PREDEFINED_SCENARIOS
    if args.scenario:
        scenarios = [s for s in PREDEFINED_SCENARIOS if args.scenario.lower() in s.name.lower()]
        if not scenarios:
            print(f"Error: No scenario matching '{args.scenario}' found.")
            return 1

    runner = ScenarioRunner(
        output_dir=args.output,
        baseline_dir=args.baseline,
        max_mismatch_pct=args.tolerance,
    )

    print(f"Running {len(scenarios)} visual scenario(s)...")
    reports = asyncio.run(runner.run_all(scenarios))

    passed = sum(1 for r in reports if r.status == "PASSED")
    failed = sum(1 for r in reports if r.status != "PASSED")
    print(f"Results: {passed} passed, {failed} failed / mismatched.")
    print(f"Gallery written to: {runner.output_dir / 'gallery.md'}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
