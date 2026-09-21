"""LangChain-compatible ports without a mandatory provider dependency."""

from .model import ChatModelAdapter, FakeModel, FakeModelRegistry, ModelCall, ModelError, ModelPort
from .prompt import PromptError, PromptTemplate, PromptTemplateRegistry
from .parser import ParseError, StructuredOutputParser
from .retriever import InMemoryRetriever, RetrievedDocument, RetrieverError, RetrieverPort
from .tool import ToolError, ToolRegistry, ToolSpec
from .compatibility import CompatibilityWindow, V3_COMPATIBILITY, assert_compatible, assert_locked

__all__ = [
    "ChatModelAdapter", "FakeModel", "FakeModelRegistry", "InMemoryRetriever", "ModelCall",
    "ModelError", "ModelPort", "ParseError", "PromptError", "PromptTemplate",
    "PromptTemplateRegistry", "RetrievedDocument", "RetrieverError", "RetrieverPort",
    "StructuredOutputParser", "ToolError", "ToolRegistry", "ToolSpec",
    "CompatibilityWindow", "V3_COMPATIBILITY", "assert_compatible", "assert_locked",
]
