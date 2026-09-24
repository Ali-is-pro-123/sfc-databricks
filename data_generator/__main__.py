"""Run with uv run python -m data_generator."""

import argparse
import json
from pathlib import Path

from .config import Config, PROFILES
from .engine import generate
from .evidence import evidence
from .validate import validate


def main():
    parser = argparse.ArgumentParser(description="Generate and verify linked DineIQ data")
    parser.add_argument("--profile", choices=PROFILES, default="small")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-07-01", help="Exclusive end date")
    parser.add_argument("--corruption-rate", type=float, default=.01)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if not args.validate_only:
        config = Config(args.profile, args.seed, args.start, args.end, args.corruption_rate)
        generate(config, args.output)
    result = validate(args.output)
    scenarios = evidence(args.output)
    manifest = json.loads((args.output / "manifest.json").read_text())
    if manifest["profile"] == "full" and not scenarios["all_passed"]:
        raise ValueError("Full dataset scenario checks failed; review evaluation/scenario_evidence.json")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
