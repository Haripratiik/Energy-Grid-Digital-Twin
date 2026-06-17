"""CLI: compare control policies across the scenario library.

Usage (from city-twin/backend):
    python -m eval.run_eval                 # all scenarios, baseline controllers
    python -m eval.run_eval --scenario gen_dropout_gas3
    python -m eval.run_eval --llm           # also include the GPT-4o controller
"""

from __future__ import annotations

import argparse
import os

from .controllers import Controller, DoNothingController, GreedyRuleController, LLMController
from .harness import compare, format_table
from .scenario import scenario_library


def _build_controllers(use_llm: bool) -> list[Controller]:
    controllers: list[Controller] = [DoNothingController(), GreedyRuleController()]
    if use_llm:
        from reasoning.engine import ReasoningEngine
        api_key = os.getenv("OPENAI_API_KEY", "")
        demo = not api_key or api_key == "your-api-key-here"
        controllers.append(LLMController(ReasoningEngine(api_key, demo_mode=demo)))
    return controllers


def main() -> None:
    ap = argparse.ArgumentParser(description="GridWorld controller evaluation")
    ap.add_argument("--scenario", help="run a single scenario by id")
    ap.add_argument("--llm", action="store_true", help="include the GPT-4o controller")
    ap.add_argument("--db", help="persist results to a SQLite database at this path")
    args = ap.parse_args()

    db = None
    if args.db:
        from storage import GridStore
        db = GridStore(args.db)

    library = scenario_library()
    if args.scenario:
        if args.scenario not in library:
            raise SystemExit(f"Unknown scenario {args.scenario!r}. "
                             f"Available: {', '.join(library)}")
        scenarios = [library[args.scenario]]
    else:
        scenarios = list(library.values())

    controllers = _build_controllers(args.llm)

    for scenario in scenarios:
        print(f"\n=== {scenario.id} ({scenario.family}) ===")
        print(scenario.description)
        results = compare(scenario, controllers)
        print(format_table(results))
        best = results[0]
        print(f"  winner: {best.controller}  (cost {best.cost:.1f})")
        if db is not None:
            for m in results:
                db.record_eval_run(m.model_dump(), seed=scenario.seed)

    if db is not None:
        db.close()


if __name__ == "__main__":
    main()
