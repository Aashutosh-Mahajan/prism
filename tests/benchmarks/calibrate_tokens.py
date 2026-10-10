"""Manual Anthropic token calibration; --prepare is offline, --measure explicitly uses the API.

python -m tests.benchmarks.calibrate_tokens --prepare
python -m tests.benchmarks.calibrate_tokens --measure --model claude-sonnet-5-5
Credentials are read from ANTHROPIC_API_KEY and never printed or stored.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import urllib.request
from pathlib import Path

from prism.core.tokens import estimate_tokens

ROOT = Path(__file__).resolve().parents[2]


def samples() -> list[dict[str, object]]:
    packets = []
    for name in ("replay_precision", "packet_audit"):
        report = json.loads((ROOT / f"output/benchmarks/{name}.json").read_text(encoding="utf-8"))
        for row in report["rows"]:
            text = row["packet"]
            digits = len(re.findall(r"[\d{}\[\]]", text)) / max(1, len(text))
            kind = "digits-json" if digits > 0.12 else "code" if "```" in text else "prose"
            packets.append({"kind": kind, "text": text, "estimate": estimate_tokens(text)})
    if len(packets) < 50:
        raise ValueError("Run T00 to collect at least 50 packets first")
    return packets[:50]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--measure", action="store_true")
    parser.add_argument("--model", action="append")
    args = parser.parse_args()
    packets = samples()
    result = {
        "status": "prepared; API measurement pending",
        "sample_count": len(packets),
        "default_scale": 1.0,
        "groups": {
            kind: sum(p["kind"] == kind for p in packets)
            for kind in ("code", "prose", "digits-json")
        },
        "models": {},
    }
    if args.measure:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            parser.error("ANTHROPIC_API_KEY is required; no request was made")
        for model in args.model or [
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            "claude-fable-5-1",
            "claude-haiku-5-5",
        ]:
            ratios = []
            for packet in packets:
                body = json.dumps(
                    {"model": model, "messages": [{"role": "user", "content": packet["text"]}]}
                ).encode()
                request = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages/count_tokens",
                    data=body,
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    count = json.load(response)["input_tokens"]
                ratios.append(count / max(1, int(packet["estimate"])))
            result["models"][model] = {"mean_ratio": statistics.mean(ratios), "ratios": ratios}
        result["status"] = "measured"
    target = ROOT / "docs/benchmarks/token-calibration.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"])


if __name__ == "__main__":
    main()
