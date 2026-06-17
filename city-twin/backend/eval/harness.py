"""Head-to-head controller comparison over scenarios."""

from __future__ import annotations

from .controllers import Controller
from .metrics import RolloutMetrics
from .runner import run_scenario
from .scenario import Scenario


def compare(scenario: Scenario, controllers: list[Controller]) -> list[RolloutMetrics]:
    """Run every controller on one scenario; return metrics sorted by cost."""
    results = [run_scenario(scenario, c).metrics for c in controllers]
    results.sort(key=lambda m: m.cost)
    return results


def run_suite(
    scenarios: list[Scenario],
    controllers: list[Controller],
) -> dict[str, list[RolloutMetrics]]:
    """Run every controller on every scenario, keyed by scenario id."""
    return {s.id: compare(s, controllers) for s in scenarios}


def format_table(results: list[RolloutMetrics]) -> str:
    """Render a comparison table for one scenario."""
    header = (
        f"{'controller':<14}{'cost':>10}{'shed_MW':>9}{'maxΔf':>8}"
        f"{'∫Δf':>9}{'maxLoad%':>10}{'viol_s':>8}{'recov_s':>9}{'secure':>8}"
    )
    lines = [header, "-" * len(header)]
    for m in results:
        recov = "-" if m.time_to_recover_s is None else f"{m.time_to_recover_s:.1f}"
        lines.append(
            f"{m.controller:<14}{m.cost:>10.1f}{m.load_shed_mw:>9.1f}"
            f"{m.max_freq_dev_hz:>8.3f}{m.integrated_freq_dev_hz_s:>9.2f}"
            f"{m.max_line_loading_pct:>10.0f}{m.violation_seconds:>8.1f}"
            f"{recov:>9}{('yes' if m.final_secure else 'NO'):>8}"
        )
    return "\n".join(lines)
