"""Immutable, versioned prompt templates with bounded interpolation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


class PromptError(ValueError): pass


@dataclass(frozen=True)
class PromptTemplate:
    key: str
    version: int
    template: str
    input_variables: tuple[str, ...]
    status: str = "active"

    def render(self, values: Mapping[str, Any]) -> str:
        missing = set(self.input_variables) - set(values)
        if missing:
            raise PromptError(f"missing prompt variables: {sorted(missing)}")
        extra = set(values) - set(self.input_variables)
        if extra:
            raise PromptError(f"unexpected prompt variables: {sorted(extra)}")
        if any(str(key).lower() in {"token", "secret", "password", "authorization"} for key in values):
            raise PromptError("sensitive prompt variable is forbidden")
        rendered = self.template
        for key in self.input_variables:
            value = values[key]
            if not isinstance(value, str) or len(value) > 4096:
                raise PromptError(f"prompt variable {key} must be bounded text")
            rendered = rendered.replace("{{" + key + "}}", value)
        if len(rendered) > 32768:
            raise PromptError("rendered prompt is too large")
        return rendered


class PromptTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, int], PromptTemplate] = {}

    def register(self, template: PromptTemplate) -> PromptTemplate:
        if template.version < 1 or not template.key.strip() or (template.key, template.version) in self._templates:
            raise PromptError("prompt version is invalid or already exists")
        placeholders = tuple(sorted(set(re.findall(r"\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}", template.template))))
        if tuple(sorted(template.input_variables)) != placeholders:
            raise PromptError("input_variables must exactly match template placeholders")
        self._templates[(template.key, template.version)] = template
        return template

    def resolve(self, key: str, version: int | None = None) -> PromptTemplate:
        if version is not None:
            try: return self._templates[(key, int(version))]
            except KeyError as exc: raise PromptError("prompt version not found") from exc
        candidates = [value for (name, _), value in self._templates.items() if name == key and value.status == "active"]
        if not candidates: raise PromptError("active prompt not found")
        return max(candidates, key=lambda item: item.version)


__all__ = ["PromptError", "PromptTemplate", "PromptTemplateRegistry"]
