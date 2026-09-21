import pytest

from integrations.langchain.compatibility import V3_COMPATIBILITY, assert_compatible


def test_compatibility_window_is_explicit_and_rejects_other_lines():
    assert V3_COMPATIBILITY.python == "3.12"
    assert_compatible(python_line="3.12", langgraph_line="0.6.7", langchain_core_line="0.3.72")
    with pytest.raises(RuntimeError): assert_compatible(python_line="3.13", langgraph_line="0.6.7", langchain_core_line="0.3.72")
