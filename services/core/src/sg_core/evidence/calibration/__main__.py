"""Run the judge against the labeled set and save the report the Quality page reads.

uv run python -m sg_core.evidence.calibration            # needs OPENROUTER_API_KEY
uv run python -m sg_core.evidence.calibration --check    # validate the labeled set only
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sg_core.evidence.calibration import (
    REPORT_PATH,
    concept_catalog,
    load_labeled_set,
    run_calibration,
    save_report,
)
from sg_core.evidence.judge import JUDGE_VERSION, LLMJudge


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--check", action="store_true", help="validate the labeled set, call no model")
    p.add_argument("--model", help="judge model (default JUDGE_MODEL)")
    p.add_argument("--out", default=str(REPORT_PATH), help="where to write the report")
    args = p.parse_args()

    labeled = load_labeled_set()
    missing = sorted({i.concept for i in labeled.items} - concept_catalog().keys())
    if missing:
        print(f"unknown concepts in labeled set: {missing}", file=sys.stderr)
        return 2
    if args.check:
        print(f"{len(labeled.items)} items ok (synthetic={labeled.synthetic})")
        return 0

    from sg_core.providers.llm import llm_client_from_settings
    from sg_core.settings import get_settings

    model = args.model or get_settings().judge_model
    judge = LLMJudge(llm_client_from_settings(), model)
    report = asyncio.run(run_calibration(judge, labeled, judge_version=JUDGE_VERSION))
    save_report(report, Path(args.out))
    print(
        f"{report['disagreements']}/{report['items']} disagree "
        f"({report['disagreement_rate']:.1%}), {report['severe_disagreements']} severe "
        f"-> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
