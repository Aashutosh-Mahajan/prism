"""Regression checks for native Codex benchmark token accounting."""

import json

from tests.benchmarks.agent_measure import summarise


def test_cached_input_is_not_counted_twice_and_duplicate_events_are_ignored(tmp_path):
    usage = {
        "type": "token_usage_record",
        "payload": {
            "response_id": "response-1",
            "usage": {
                "input_tokens": 1000,
                "cached_input_tokens": 800,
                "output_tokens": 20,
            },
        },
    }
    call = {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": "call-1",
            "name": "functions.exec",
            "input": "await tools.exec_command({})",
        },
    }
    output = {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": "call-1",
            "output": "a" * 40,
        },
    }
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in [usage, usage, call, call, output, output])
        + '\n{"partial":',
        encoding="utf-8",
    )
    result = summarise(path)
    assert result["model_turns"] == 1
    assert result["total_input_processed"] == 1000
    assert result["billable_input_equiv_proxy"] == 280
    assert result["tool_calls"] == 1
    assert result["nested_shell_call_sites"] == 1
    assert result["tool_output_tokens_est"] == 10


def test_missing_usage_is_unknown_for_context(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    result = summarise(path)
    assert result["first_turn_context"] is None
    assert result["work_context"] is None
    assert result["duration_seconds"] is None


def test_native_final_answer_phase_is_collected(tmp_path):
    path = tmp_path / "final.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "Diagnosis"}],
                },
            }
        ),
        encoding="utf-8",
    )
    assert summarise(path)["final_answer"] == "Diagnosis"


def test_scoring_does_not_promote_a_dependent_to_primary(tmp_path):
    from tests.benchmarks.agent_score import score

    key = [{"task": n, "target": "module.expected", "direct_callers": []} for n in range(1, 13)]
    for run in range(1, 4):
        base = tmp_path / f"run-{run}"
        (base / "without" / "backend").mkdir(parents=True)
        (base / "answer-key.json").write_text(json.dumps(key), encoding="utf-8")
        (base / "without" / "backend" / "tests.py").write_text(
            "class ExistingTests: pass\n", encoding="utf-8"
        )
    answer = "\n\n".join(
        f"Task {n}: primary function = module.other, location = f.py:1-2; "
        "Why: diagnosis; Callers/dependents to check: module.expected; Tests to run: none found."
        for n in range(1, 13)
    )
    (tmp_path / "run1_without-answer.md").write_text(answer, encoding="utf-8")
    result = score(tmp_path)["run1_without"]
    assert result["correct"] == 0
    assert result["partial"] == 12
    assert result["tasks_with_existing_backend_tests_named"] == 0


def test_mcp_protocol_call_counts_come_from_wire_requests(tmp_path):
    from tests.benchmarks.agent_collect import mcp_metrics

    rows = [
        {"direction": "lifecycle", "message": {"event": "server_started"}},
        {"direction": "send", "message": {"id": 1, "method": "initialize"}},
        {"direction": "receive", "message": {"id": 1, "result": {}}},
        {"direction": "send", "message": {"id": 2, "method": "tools/list"}},
        {
            "direction": "send",
            "message": {"id": 3, "method": "tools/call", "params": {"name": "prism_search"}},
        },
        {"direction": "receive", "message": {"id": 3, "result": {"content": []}}},
        {
            "direction": "send",
            "message": {"id": 4, "method": "tools/call", "params": {"name": "prism_context"}},
        },
        {"direction": "receive", "message": {"id": 4, "error": {"code": -32602}}},
    ]
    path = tmp_path / "mcp.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    result = mcp_metrics(path)
    assert result["mcp_server_starts"] == 1
    assert result["mcp_tool_calls"] == 2
    assert result["mcp_tool_responses"] == 2
    assert result["mcp_protocol_errors"] == 1
    assert result["mcp_tools"] == {"prism_search": 1, "prism_context": 1}


def test_prism_cli_audit_does_not_count_mcp_names(tmp_path):
    path = tmp_path / "rollout.jsonl"
    row = {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": "test",
            "name": "functions.exec",
            "input": "prism1.call('prism_search',{}); tools.exec_command({cmd:'prism brief'})",
        },
    }
    path.write_text(json.dumps(row), encoding="utf-8")
    assert summarise(path)["prism_cli_command_sites"] == 1


def test_primary_owner_disambiguates_an_inherited_method_name():
    from tests.benchmarks.agent_score import matches_primary

    assert matches_primary(
        "zesty.views.RestaurantViewSet.get_object",
        "backend.zesty.views.RestaurantViewSet.get_object",
    )
    assert not matches_primary(
        "RestaurantDetailAPIView (inherited get_object lookup)",
        "backend.zesty.views.RestaurantViewSet.get_object",
    )
