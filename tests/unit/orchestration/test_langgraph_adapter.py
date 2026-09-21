from uuid import uuid4

from orchestration import GraphDefinition
from orchestration.langgraph_adapter import compile_langgraph


def test_real_langgraph_composition_runs_validated_reference_state_and_checkpoints():
    definition = GraphDefinition(
        "content", 1,
        nodes=(lambda state: {"result_refs": {"brief": "private://brief/1"}},
               lambda state: {"result_refs": {"qa": "ref://qa/pass"}}),
    )
    executable = compile_langgraph(definition)
    run_id, org_id = str(uuid4()), str(uuid4())
    result = executable.invoke({
        "run_id": run_id, "org_id": org_id, "workflow_key": "content", "workflow_version": 1,
        "input_refs": {"signal": "ref://signal/1"}, "trace_id": "trace", "state_version": 1,
    }, thread_id=run_id)
    assert result["result_refs"] == {"brief": "private://brief/1", "qa": "ref://qa/pass"}
