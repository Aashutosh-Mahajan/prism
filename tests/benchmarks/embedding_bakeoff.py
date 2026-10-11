"""Pinned local embedding comparison over historical T40 trees and real code twins."""

from __future__ import annotations

import argparse
import ast
import copy
import ctypes
import hashlib
import io
import json
import os
import subprocess
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def prepare(report: Path, output: Path) -> None:
    from prism.navigator.semantic import symbol_text
    from prism.parsing.python_ast import PythonAstParser

    replay = json.loads(report.read_text(encoding="utf-8"))
    documents: dict[str, str] = {}
    trees: dict[str, list[dict[str, str]]] = {}
    twins: dict[str, list[dict[str, str]]] = defaultdict(list)
    parser = PythonAstParser()
    references = list(dict.fromkeys([row["parent"] for row in replay["rows"]]))
    for number, revision in enumerate(references):
        archive = subprocess.run(
            ["git", "archive", "--format=zip", revision], cwd=ROOT, capture_output=True, check=True
        ).stdout
        records = []
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            for path in sorted(files.namelist()):
                if not path.endswith(".py") or path.startswith(
                    ("tests/fixtures/", "tests/golden/", "output/")
                ):
                    continue
                source = files.read(path)
                module = path.removesuffix(".py").replace("/", ".")
                parsed = parser.parse(path, source, module, False)
                lines = source.decode("utf-8", "replace").splitlines()
                for symbol in parsed.symbols:
                    row = SimpleNamespace(
                        kind=symbol.kind,
                        name=symbol.name,
                        signature=symbol.signature,
                        doc=symbol.doc,
                        parent=symbol.parent,
                        start=symbol.lines[0],
                        end=symbol.lines[1],
                    )
                    text = symbol_text(row, lines)
                    digest = hashlib.sha256(text.encode()).hexdigest()
                    documents[digest] = text
                    records.append(
                        {"id": module + "." + symbol.qualname, "file": path, "doc": digest}
                    )
                if number == 0:
                    try:
                        tree = ast.parse(source)
                    except (SyntaxError, UnicodeError):
                        continue
                    for node in ast.walk(tree):
                        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            continue
                        normalized = copy.deepcopy(node)
                        normalized.name = "_function"
                        if (
                            normalized.body
                            and isinstance(normalized.body[0], ast.Expr)
                            and isinstance(normalized.body[0].value, ast.Constant)
                            and isinstance(normalized.body[0].value.value, str)
                        ):
                            normalized.body.pop(0)
                        if sum(1 for _ in ast.walk(normalized)) < 20:
                            continue
                        match = next(
                            (
                                s
                                for s in parsed.symbols
                                if s.name == node.name and s.lines[1] == node.end_lineno
                            ),
                            None,
                        )
                        if match is not None:
                            twins[ast.dump(normalized)].append(
                                {
                                    "id": module + "." + match.qualname,
                                    "file": path,
                                    "query": "\n".join(lines[node.lineno - 1 : node.end_lineno])[
                                        :600
                                    ],
                                }
                            )
        trees[revision] = records
        print(f"Prepared tree {number + 1}/{len(references)}", flush=True)
    code_cases = []
    for _fingerprint, group in sorted(twins.items(), key=lambda item: (-len(item[0]), item[0])):
        if len({row["file"] for row in group}) < 2:
            continue
        group = sorted(group, key=lambda row: row["id"])
        query = group[0]
        code_cases.append(
            {
                "query": query["query"],
                "exclude": query["id"],
                "gold": sorted({row["id"] for row in group[1:] if row["file"] != query["file"]}),
            }
        )
        if len(code_cases) == 20:
            break
    data = {
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "source_head": replay["source_head"],
        "representation": "production symbol_text, 600 characters, first 8 body lines",
        "documents": documents,
        "trees": trees,
        "cases": [
            {"parent": row["parent"], "query": row["query"], "gold": row["gold"]}
            for row in replay["rows"]
        ],
        "code_parent": references[0],
        "code_cases": code_cases,
    }
    output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def peak_memory() -> int | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = wintypes.HANDLE
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
    return (
        int(counters.PeakWorkingSetSize)
        if get_memory(current(), ctypes.byref(counters), counters.cb)
        else None
    )


def run(dataset: Path, model: Path, kind: str, output: Path) -> None:
    run_started = time.time()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import numpy as np

    data = json.loads(dataset.read_text(encoding="utf-8"))
    started = time.perf_counter()
    if kind == "minilm":
        from prism.navigator.bert_numpy import NumpyBertEmbedder

        embedder = NumpyBertEmbedder(str(model.resolve()))

        def encode(texts, query=False):
            return np.asarray(embedder.embed(texts), dtype=np.float32)

        device = "cpu/numpy"
    else:
        import torch
        from transformers import AutoModel, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            model, local_files_only=True, trust_remote_code=False
        )
        network = AutoModel.from_pretrained(model, local_files_only=True, trust_remote_code=False)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        network.to(device).eval()

        def encode(texts, query=False):
            if query:
                texts = [
                    "Represent this query for searching relevant code: " + text for text in texts
                ]
            results = []
            with torch.inference_mode():
                for offset in range(0, len(texts), 16):
                    inputs = tokenizer(
                        texts[offset : offset + 16],
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    ).to(device)
                    vectors = network(**inputs).last_hidden_state[:, 0]
                    results.append(
                        torch.nn.functional.normalize(vectors.float(), dim=1).cpu().numpy()
                    )
            return np.concatenate(results)

    cold = time.perf_counter() - started
    digests = sorted(data["documents"])
    positions = {digest: i for i, digest in enumerate(digests)}
    started = time.perf_counter()
    vectors = encode([data["documents"][digest] for digest in digests])
    index_seconds = time.perf_counter() - started
    rows = []
    for case in data["cases"]:
        query = encode([case["query"]], query=True)[0]
        candidates = data["trees"][case["parent"]]
        scores = vectors[[positions[row["doc"]] for row in candidates]] @ query
        ranked = sorted(
            range(len(candidates)), key=lambda i: (-float(scores[i]), candidates[i]["id"])
        )
        files = list(dict.fromkeys(candidates[i]["file"] for i in ranked))
        rows.append(
            {
                "query": case["query"],
                "gold": case["gold"],
                "top10": files[:10],
                "hits5": len(set(case["gold"]) & set(files[:5])),
                "hits10": len(set(case["gold"]) & set(files[:10])),
            }
        )
    code_rows = []
    for case in data["code_cases"]:
        candidates = [
            row for row in data["trees"][data["code_parent"]] if row["id"] != case["exclude"]
        ]
        query = encode([case["query"]], query=True)[0]
        scores = vectors[[positions[row["doc"]] for row in candidates]] @ query
        ranked = sorted(
            range(len(candidates)), key=lambda i: (-float(scores[i]), candidates[i]["id"])
        )
        ids = [candidates[i]["id"] for i in ranked[:10]]
        code_rows.append(
            {
                "exclude": case["exclude"],
                "gold": case["gold"],
                "top10": ids,
                "hits5": len(set(case["gold"]) & set(ids[:5])),
                "hits10": len(set(case["gold"]) & set(ids[:10])),
            }
        )
    timings = []
    for _ in range(30):
        started = time.perf_counter()
        encode([data["cases"][0]["query"]], query=True)
        timings.append(time.perf_counter() - started)
    denominator = sum(len(row["gold"]) for row in rows)
    code_denominator = sum(len(row["gold"]) for row in code_rows)
    result = {
        "run_started_unix": run_started,
        "run_finished_unix": time.time(),
        "model": kind,
        "device": device,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "cold_seconds": cold,
        "index_seconds": index_seconds,
        "vector_bytes": vectors.nbytes,
        "unique_symbol_texts": len(digests),
        "peak_working_set_bytes": peak_memory(),
        "warm_query_median_ms": float(np.median(timings) * 1000),
        "warm_query_p95_ms": float(np.percentile(timings, 95) * 1000),
        "file_gold_total": denominator,
        "file_recall5": sum(row["hits5"] for row in rows) / denominator,
        "file_recall10": sum(row["hits10"] for row in rows) / denominator,
        "code_cases": len(code_rows),
        "code_recall5": sum(row["hits5"] for row in code_rows) / code_denominator
        if code_denominator
        else None,
        "code_recall10": sum(row["hits10"] for row in code_rows) / code_denominator
        if code_denominator
        else None,
        "rows": rows,
        "code_rows": code_rows,
        "warm_query_seconds": timings,
        "remote_code_trust": False,
        "api_spend": 0,
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"rows", "code_rows", "warm_query_seconds"}
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "run"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--kind", choices=("minilm", "coderank"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation == "prepare":
        if args.report is None:
            parser.error("prepare requires --report")
        prepare(args.report, args.dataset)
    else:
        if args.model is None or args.kind is None or args.output is None:
            parser.error("run requires --model --kind --output")
        run(args.dataset, args.model, args.kind, args.output)


if __name__ == "__main__":
    main()
