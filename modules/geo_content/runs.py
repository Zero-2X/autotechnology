"""Deterministic offline multi-sample GEO runs for GEO_CONTENT-003.

``GeoRunService`` consumes only caller supplied answer fixtures through the
``FakeGeo`` port.  It parses each captured answer with the GEO_CONTENT-002
deterministic sampler, removes duplicate observations, and emits a closed
``GeoRun`` projection.  The module performs no network or provider I/O.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .fixtures import (
    GeoQueryFixtureError,
    GeoQueryFixtureService,
    _guard_nested_tenant,
    _hash,
    _policy_hash,
    _resolve_tenant,
    _safe_tenant,
    _stamp,
    _text,
    _uuid,
    validate_fixture_integrity,
    validate_predecessors,
)
from .sampling import (
    ComplianceSamplingPort,
    DeterministicComplianceSampler,
    _validate_sample_output,
)


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/geo-run.schema.json").read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_RUN_NAMESPACE = UUID("6f736c3e-16e6-5268-86ef-739ec78fde03")
_ANSWER_FIELDS = ("answers", "samples", "results", "responses")


class GeoRunError(GeoQueryFixtureError):
    """Stable machine readable failure for a GEO_CONTENT-003 command."""


class FakeGeoPort(Protocol):
    """Offline port that returns captured answer fixture entries."""

    def collect(
        self,
        *,
        sample_count: int,
        answer_fixture: Any = None,
        query_fixture: Mapping[str, Any] | None = None,
    ) -> Sequence[Any]: ...


def _answer_sequence(value: Any, *, field: str) -> list[Any]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise GeoRunError("INVALID_ANSWER_FIXTURE", f"{field} must be an array")
    answers = list(value)
    for index, answer in enumerate(answers):
        if answer is not None and not isinstance(answer, (str, Mapping)):
            raise GeoRunError(
                "INVALID_ANSWER_FIXTURE",
                f"{field}[{index}] must be text, an object, or null",
            )
        try:
            # Validate finite JSON without retaining the raw answer anywhere.
            json.dumps(answer, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise GeoRunError(
                "INVALID_ANSWER_FIXTURE", f"{field}[{index}] must be finite JSON"
            ) from exc
    return answers


class FakeGeo:
    """A deterministic, account free source of captured answer fixtures.

    Answers may be supplied when constructing the port or on each call.  A
    mapping wrapper may use exactly one of ``answers``, ``samples``,
    ``results``, or ``responses`` and may bind itself to the query fixture via
    ``query_fixture_id``/``fixture_id`` and ``fixture_hash``.
    """

    def __init__(self, answers: Any = None, *, answer_fixture: Any = None) -> None:
        if answers is not None and answer_fixture is not None:
            raise GeoRunError("AMBIGUOUS_ANSWER_FIXTURE", "provide one default answer fixture")
        self._default = deepcopy(answer_fixture if answer_fixture is not None else answers)

    @staticmethod
    def _unwrap(
        value: Any,
        *,
        query_fixture: Mapping[str, Any] | None,
    ) -> list[Any]:
        if query_fixture is not None:
            try:
                fixture_tenant = _uuid(query_fixture.get("org_id"), "query_fixture.org_id")
                assert fixture_tenant is not None
                _guard_nested_tenant(value, fixture_tenant, "answer_fixture")
            except GeoQueryFixtureError as exc:
                raise GeoRunError(
                    exc.code,
                    str(exc),
                    details=getattr(exc, "details", None),
                ) from exc
        if isinstance(value, Mapping):
            present = [name for name in _ANSWER_FIELDS if name in value]
            if len(present) != 1:
                raise GeoRunError(
                    "AMBIGUOUS_ANSWER_FIXTURE" if present else "INVALID_ANSWER_FIXTURE",
                    "answer fixture must contain exactly one answer collection",
                )
            if query_fixture is not None:
                try:
                    expected_uuid = _uuid(query_fixture.get("id"), "query_fixture.id")
                    assert expected_uuid is not None
                except Exception as exc:
                    raise GeoRunError(
                        "INVALID_ANSWER_FIXTURE", "query fixture identifier must be a UUID"
                    ) from exc
                bound_ids = [value[name] for name in ("query_fixture_id", "fixture_id") if name in value]
                if len(bound_ids) > 1:
                    try:
                        first_uuid = _uuid(bound_ids[0], "answer_fixture.query_fixture_id")
                        second_uuid = _uuid(bound_ids[1], "answer_fixture.fixture_id")
                    except Exception as exc:
                        raise GeoRunError(
                            "INVALID_ANSWER_FIXTURE", "answer fixture identifier must be a UUID"
                        ) from exc
                    if first_uuid != second_uuid:
                        raise GeoRunError("ANSWER_FIXTURE_MISMATCH", "answer fixture identifiers disagree")
                if bound_ids:
                    try:
                        bound_id = _uuid(bound_ids[0], "answer_fixture.fixture_id")
                        assert bound_id is not None
                    except Exception as exc:
                        raise GeoRunError(
                            "INVALID_ANSWER_FIXTURE", "answer fixture identifier must be a UUID"
                        ) from exc
                    if bound_id != expected_uuid:
                        raise GeoRunError(
                            "ANSWER_FIXTURE_MISMATCH", "answer fixture belongs to another query fixture"
                        )
                if "fixture_hash" in value and value["fixture_hash"] != query_fixture.get("fixture_hash"):
                    raise GeoRunError(
                        "ANSWER_FIXTURE_MISMATCH", "answer fixture hash does not match query fixture"
                    )
                for field in ("locale", "region"):
                    if field in value and value[field] != query_fixture.get(field):
                        raise GeoRunError(
                            "ANSWER_FIXTURE_MISMATCH", f"answer fixture {field} does not match query fixture"
                        )
                if "parser_version" in value and value["parser_version"] != query_fixture.get("_parser_version"):
                    raise GeoRunError(
                        "ANSWER_FIXTURE_MISMATCH", "answer fixture parser version does not match sampler"
                    )
            answers = _answer_sequence(value[present[0]], field=f"answer_fixture.{present[0]}")
            if "answer_fixture_hash" in value and value["answer_fixture_hash"] != _hash(answers):
                raise GeoRunError(
                    "ANSWER_FIXTURE_HASH_MISMATCH", "answer fixture content hash does not match answers"
                )
            return answers
        return _answer_sequence(value, field="answer_fixture")

    def collect(
        self,
        *,
        sample_count: int,
        answer_fixture: Any = None,
        query_fixture: Mapping[str, Any] | None = None,
    ) -> tuple[Any, ...]:
        source = answer_fixture if answer_fixture is not None else self._default
        if source is None:
            raise GeoRunError("ANSWER_FIXTURE_REQUIRED", "offline answer fixture is required")
        answers = self._unwrap(source, query_fixture=query_fixture)
        if len(answers) < sample_count:
            raise GeoRunError(
                "INSUFFICIENT_ANSWER_SAMPLES",
                f"answer fixture has {len(answers)} samples; {sample_count} required",
            )
        return tuple(deepcopy(answers[:sample_count]))

    sample = collect
    sample_many = collect
    run = collect


class InMemoryGeoRunStore:
    """Thread safe append only port for runs, commands, and hash observations."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.request_index: dict[tuple[str, str], str] = {}
        self.observations: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, *, org_id: str, idempotency_key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.commands.get((org_id, idempotency_key))
            return deepcopy(value) if value is not None else None

    def save_command(
        self,
        *,
        org_id: str,
        idempotency_key: str,
        request_hash: str,
        response: Mapping[str, Any],
        fixture_version: int | None = None,
    ) -> None:
        row = {
            "request_hash": request_hash,
            "response": deepcopy(dict(response)),
            "fixture_version": fixture_version,
        }
        with self._lock:
            key = (org_id, idempotency_key)
            existing = self.commands.get(key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise GeoRunError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return
            self.commands[key] = row

    def get_run(self, *, org_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.runs.get((org_id, run_id))
            return deepcopy(value) if value is not None else None

    def find_run(self, *, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            for (__, identity), row in self.runs.items():
                if identity == run_id:
                    return deepcopy(row)
        return None

    def get_by_request(self, *, org_id: str, request_hash: str) -> dict[str, Any] | None:
        with self._lock:
            run_id = self.request_index.get((org_id, request_hash))
            if run_id is None:
                return None
            return deepcopy(self.runs[(org_id, run_id)])

    def save_run(
        self,
        value: Mapping[str, Any],
        *,
        request_hash: str,
        observations: Sequence[Mapping[str, Any]],
    ) -> None:
        row = deepcopy(dict(value))
        key = (str(row["org_id"]), str(row["id"]))
        request_key = (str(row["org_id"]), request_hash)
        with self._lock:
            existing = self.runs.get(key)
            if existing is not None and existing != row:
                raise GeoRunError("GEO_RUN_ID_CONFLICT", "run id belongs to another projection")
            existing_id = self.request_index.get(request_key)
            if existing_id is not None and existing_id != row["id"]:
                raise GeoRunError("GEO_RUN_REQUEST_CONFLICT", "request hash belongs to another run")
            if existing is None:
                self.runs[key] = row
                self.request_index[request_key] = str(row["id"])
                self.observations.extend(deepcopy([dict(item) for item in observations]))

    def list_runs(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = [deepcopy(row) for (tenant, __), row in self.runs.items() if tenant == org_id]
        return tuple(sorted(rows, key=lambda item: (item["created_at"], item["id"])))

    def append_audit(self, row: Mapping[str, Any]) -> None:
        with self._lock:
            self.audit.append(deepcopy(dict(row)))

    def audit_for(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == org_id)


def _validate_run(value: Mapping[str, Any]) -> None:
    errors = sorted(_VALIDATOR.iter_errors(dict(value)), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "run"
        raise GeoRunError("INVALID_GEO_RUN", f"{location}: {errors[0].message}")
    if value["mention_count"] > value["sample_count"]:
        raise GeoRunError("INVALID_GEO_RUN", "mention_count exceeds sample_count")
    if value["citation_count"] > value["sample_count"]:
        raise GeoRunError("INVALID_GEO_RUN", "citation_count exceeds sample_count")
    if value["position_values"] != sorted(set(value["position_values"])):
        raise GeoRunError("INVALID_GEO_RUN", "position_values must be sorted and unique")
    if len(value["correctness_values"]) != len(set(value["correctness_values"])):
        raise GeoRunError("INVALID_GEO_RUN", "correctness_values must be unique")
    if value["data_quality"] != "estimated":
        raise GeoRunError("INVALID_GEO_RUN", "FakeGeo runs must have estimated data quality")


class GeoRunService:
    """Run deterministic multi-sample FakeGeo aggregation for an active fixture."""

    task_id = "GEO_CONTENT-003"
    rule_version = "geo-content-003.v1"

    def __init__(
        self,
        *,
        fixture_service: GeoQueryFixtureService | None = None,
        fake_geo: FakeGeoPort | None = None,
        sampler: ComplianceSamplingPort | None = None,
        store: InMemoryGeoRunStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.fixture_service = fixture_service or GeoQueryFixtureService(clock=self.clock)
        self.fake_geo = fake_geo or FakeGeo()
        self.sampler = sampler or DeterministicComplianceSampler()
        self.store = store or InMemoryGeoRunStore()
        self.audit = self.store.audit
        self._lock = RLock()

    def _audit(
        self,
        *,
        event_type: str,
        tenant: str,
        actor: str,
        trace: str,
        idempotency_key: str | None,
        aggregate_id: str | None,
        input_hash: str | None,
        output_hash: str | None,
        fixture_version: int | None,
        policy_hash: str | None,
        status: str,
        reason: str | None = None,
        cost_cents: int = 0,
    ) -> None:
        self.store.append_audit({
            "event_type": event_type,
            "task_id": self.task_id,
            "org_id": tenant,
            "actor_id": actor,
            "trace_id": trace,
            "idempotency_key": idempotency_key,
            "aggregate_id": aggregate_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "input_version": fixture_version,
            "output_version": 1 if aggregate_id is not None else None,
            "policy_snapshot_hash": policy_hash,
            "status": status,
            "reason": reason,
            "duration_ms": 0,
            "cost_cents": max(0, int(cost_cents)),
            "created_at": _stamp(self.clock()),
        })

    def _reject(
        self,
        error: GeoQueryFixtureError,
        *,
        org_id: Any,
        tenant_context: Mapping[str, Any] | None,
        actor_id: Any,
        trace_id: Any,
        idempotency_key: Any,
        input_hash: str | None = None,
        fixture_version: int | None = None,
        policy_hash: str | None = None,
    ) -> None:
        tenant = _safe_tenant(org_id, tenant_context)
        context = tenant_context if isinstance(tenant_context, Mapping) else {}
        actor_value = actor_id if actor_id is not None else context.get("actor_id", context.get("actor"))
        trace_value = trace_id if trace_id is not None else context.get("trace_id")
        try:
            actor = _text(str(actor_value), "actor_id", maximum=256) if actor_value is not None else "unknown"
        except GeoQueryFixtureError:
            actor = "unknown"
        try:
            trace = _text(trace_value or "geo-content-003", "trace_id", maximum=256)
        except GeoQueryFixtureError:
            trace = "geo-content-003"
        self._audit(
            event_type="geo.run.rejected",
            tenant=tenant,
            actor=actor,
            trace=trace,
            idempotency_key=str(idempotency_key) if idempotency_key is not None else None,
            aggregate_id=None,
            input_hash=input_hash,
            output_hash=None,
            fixture_version=fixture_version,
            policy_hash=policy_hash,
            status="rejected",
            reason=f"{error.code}: {error}",
        )

    @staticmethod
    def _fixture_id(query_fixture_id: Any, fixture_id: Any) -> str:
        supplied = [value for value in (query_fixture_id, fixture_id) if value is not None]
        if not supplied:
            raise GeoRunError("INVALID_GEO_RUN", "query_fixture_id is required")
        identities = [_uuid(value, "query_fixture_id") for value in supplied]
        if len(identities) == 2 and identities[0] != identities[1]:
            raise GeoRunError("INVALID_GEO_RUN", "query fixture identifiers disagree")
        assert identities[0] is not None
        return identities[0]

    @staticmethod
    def _sample_count(value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 2 <= value <= 100:
            raise GeoRunError("INVALID_SAMPLE_COUNT", "sample_count must be an integer from 2 to 100")
        return value

    @staticmethod
    def _choose_answers(**candidates: Any) -> Any:
        supplied = [(name, value) for name, value in candidates.items() if value is not None]
        if len(supplied) > 1:
            raise GeoRunError("AMBIGUOUS_ANSWER_FIXTURE", "provide one offline answer fixture")
        return supplied[0][1] if supplied else None

    @staticmethod
    def _aggregate(observations: Sequence[Mapping[str, Any]], sample_count: int) -> dict[str, Any]:
        unique: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for item in observations:
            digest = str(item["result_hash"])
            if digest not in seen:
                seen.add(digest)
                unique.append(item)

        mention_count = sum(1 for item in unique if item.get("mentioned") is True)
        citation_count = sum(1 for item in unique if int(item.get("citation_count", 0)) > 0)
        positions = sorted({
            int(item["position"])
            for item in unique
            if isinstance(item.get("position"), int)
            and not isinstance(item.get("position"), bool)
            and int(item["position"]) > 0
        })
        correctness: list[str] = []
        for item in unique:
            value = str(item.get("correctness"))
            if value not in correctness:
                correctness.append(value)
        known = [item for item in unique if item.get("correctness") in {"correct", "incorrect"}]
        if not unique:
            confidence = 0.0
        else:
            signal_score = sum(
                (0.4 if item.get("mentioned") is True else 0.0)
                + (0.3 if int(item.get("citation_count", 0)) > 0 else 0.0)
                + (0.3 if item.get("correctness") == "correct" else 0.0)
                for item in unique
            ) / len(unique)
            confidence = round(
                (len(unique) / sample_count) * (len(known) / len(unique)) * signal_score,
                6,
            )
        return {
            "unique": unique,
            "mention_count": mention_count,
            "citation_count": citation_count,
            "position_values": positions,
            "correctness_values": correctness,
            "confidence": confidence,
            "status": "succeeded" if known else "failed",
        }

    def run(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        page_version_id: Any = None,
        query_fixture_id: Any = None,
        fixture_id: Any = None,
        locale: Any = None,
        region: Any = None,
        sample_count: Any = None,
        answer_fixture: Any = None,
        answers: Any = None,
        results: Any = None,
        samples: Any = None,
        responses: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        **_: Any,
    ) -> dict[str, Any]:
        self._lock.acquire()
        audit_input_hash: str | None = None
        audit_fixture_version: int | None = None
        audit_policy_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            page_id = _uuid(page_version_id, "page_version_id")
            assert page_id is not None
            query_id = self._fixture_id(query_fixture_id, fixture_id)
            count = self._sample_count(sample_count)
            locale_text = _text(locale, "locale", maximum=32)
            region_text = _text(region, "region", maximum=128)
            fixture = self.fixture_service.get_fixture(org_id=tenant, fixture_id=query_id)
            # Treat the fixture service as an untrusted boundary.  A custom
            # adapter must not be able to return another tenant's fixture (or
            # a different fixture under the requested identifier) and then
            # forge a tenant-local observation around it.
            fixture_org = _uuid(fixture.get("org_id"), "query_fixture.org_id")
            fixture_identity = _uuid(fixture.get("id"), "query_fixture.id")
            if fixture_org != tenant:
                raise GeoRunError(
                    "TENANT_SCOPE_VIOLATION",
                    "query fixture belongs to another organization",
                )
            if fixture_identity != query_id:
                raise GeoRunError(
                    "FIXTURE_ID_MISMATCH",
                    "query fixture identifier does not match the request",
                )
            audit_fixture_version = int(fixture.get("version", 1))
            validate_fixture_integrity(fixture, predecessor_artifacts=predecessor_artifacts)
            validate_predecessors(predecessor_artifacts, org_id=tenant)
            parser_version = _text(
                getattr(self.sampler, "parser_version", None),
                "sampler.parser_version",
                maximum=64,
            )
            supplied = self._choose_answers(
                answer_fixture=answer_fixture,
                answers=answers,
                results=results,
                samples=samples,
                responses=responses,
            )
            try:
                captured = tuple(self.fake_geo.collect(
                    sample_count=count,
                    answer_fixture=supplied,
                    query_fixture=deepcopy({**fixture, "_parser_version": parser_version}),
                ))
            except GeoQueryFixtureError:
                raise
            except Exception as exc:
                raise GeoRunError("FAKE_GEO_FAILED", "offline FakeGeo fixture failed") from exc
            if len(captured) != count:
                raise GeoRunError("INVALID_ANSWER_FIXTURE", "FakeGeo returned an unexpected sample count")
            # Revalidate custom port output before hashing or parsing it.
            captured = tuple(_answer_sequence(captured, field="captured_answers"))
            _guard_nested_tenant(captured, tenant, "captured_answers")
            answer_hash = _hash(list(captured))
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            policy_hash = _policy_hash(policy_snapshot)
            audit_policy_hash = policy_hash
            prior = self.store.get_command(org_id=tenant, idempotency_key=key)
            hash_fixture_version = (
                int(prior["fixture_version"])
                if prior is not None and prior.get("fixture_version") is not None
                else int(fixture.get("version", 1))
            )
            audit_fixture_version = hash_fixture_version
            request_hash = _hash({
                "command": "geo_run",
                "org_id": tenant,
                "page_version_id": page_id,
                "query_fixture_id": query_id,
                "fixture_version": hash_fixture_version,
                "fixture_hash": fixture["fixture_hash"],
                "locale": locale_text,
                "region": region_text,
                "sample_count": count,
                "parser_version": parser_version,
                "answer_fixture_hash": answer_hash,
                "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                "policy_snapshot_hash": policy_hash,
            })
            audit_input_hash = request_hash
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise GeoRunError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            if fixture.get("status") != "active":
                raise GeoRunError("FIXTURE_NOT_ACTIVE", "query fixture must be active")
            if locale_text != fixture.get("locale"):
                raise GeoRunError("FIXTURE_LOCALE_MISMATCH", "locale does not match query fixture")
            if region_text != fixture.get("region"):
                raise GeoRunError("FIXTURE_REGION_MISMATCH", "region does not match query fixture")
            existing = self.store.get_by_request(org_id=tenant, request_hash=request_hash)
            if existing is not None:
                self.store.save_command(
                    org_id=tenant,
                    idempotency_key=key,
                    request_hash=request_hash,
                    response=existing,
                    fixture_version=int(fixture.get("version", 1)),
                )
                return existing

            parsed: list[dict[str, Any]] = []
            for answer in captured:
                try:
                    value = self.sampler.sample(
                        fixture=deepcopy(fixture),
                        result=deepcopy(answer),
                        predecessor_artifacts=deepcopy(predecessor_artifacts),
                        policy_snapshot=deepcopy(policy_snapshot),
                    )
                    if not isinstance(value, Mapping):
                        raise TypeError("sampler result must be an object")
                    observation = dict(value)
                    expected_input_hash = _hash({
                        "fixture_id": fixture["id"],
                        "fixture_hash": fixture["fixture_hash"],
                        "result": deepcopy(answer),
                        "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                        "policy_snapshot_hash": policy_hash,
                    })
                    if observation.get("input_hash") != expected_input_hash:
                        raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample input hash mismatch")
                    expected_output_hash = _hash({
                        name: item
                        for name, item in observation.items()
                        if name != "output_hash"
                    })
                    if observation.get("output_hash") != expected_output_hash:
                        raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample output hash mismatch")
                    # GEO_CONTENT-002 attaches these two boundary fields in
                    # its command service.  GEO_CONTENT-003 calls the pure
                    # parser port directly, so bind the same invariants here
                    # before applying the shared validator.
                    observation["fixture_version"] = int(fixture.get("version", 1))
                    observation["duration_ms"] = 0
                    _validate_sample_output(observation)
                except GeoQueryFixtureError as exc:
                    raise GeoRunError(
                        "INVALID_GEO_RUN_SAMPLE", "offline sample could not be parsed",
                        details={"cause": exc.code},
                    ) from exc
                except Exception as exc:
                    raise GeoRunError("SAMPLING_PORT_FAILED", "offline sampling adapter failed") from exc
                if observation.get("fixture_hash") != fixture["fixture_hash"]:
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample fixture hash mismatch")
                if observation.get("parser_version") != parser_version:
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample parser version mismatch")
                if observation.get("result_hash") != _hash(answer):
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample result hash mismatch")
                expected_fields = {
                    "fixture_id": fixture["id"],
                    "org_id": tenant,
                    "query": fixture["query"],
                    "locale": fixture["locale"],
                    "region": fixture["region"],
                }
                if any(observation.get(name) != expected for name, expected in expected_fields.items()):
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample fixture projection mismatch")
                for field in ("mention_count", "citation_count"):
                    value = observation.get(field)
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise GeoRunError("INVALID_GEO_RUN_SAMPLE", f"sample {field} is invalid")
                if observation["mentioned"] != any(
                    item["mentioned"] for item in observation["mentions"]
                ):
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample mention summary mismatch")
                if [item["entity"] for item in observation["mentions"]] != list(
                    fixture.get("expected_entities", [])
                ):
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample entity projection mismatch")
                expected_status = {
                    "correct": "pass",
                    "incorrect": "fail",
                    "unknown": "manual_review",
                }[observation["correctness"]]
                if observation["status"] != expected_status:
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample correctness status mismatch")
                if observation["unknown_external_result"] != (
                    observation["correctness"] == "unknown"
                ):
                    raise GeoRunError("INVALID_GEO_RUN_SAMPLE", "sample unknown status mismatch")
                parsed.append(observation)

            aggregate = self._aggregate(parsed, count)
            run_id = str(uuid5(_RUN_NAMESPACE, f"{tenant}:{request_hash}"))
            row = {
                "id": run_id,
                "org_id": tenant,
                "page_version_id": page_id,
                "query_fixture_id": query_id,
                "locale": locale_text,
                "region": region_text,
                "sample_count": count,
                "parser_version": parser_version,
                "mention_count": aggregate["mention_count"],
                "citation_count": aggregate["citation_count"],
                "position_values": aggregate["position_values"],
                "correctness_values": aggregate["correctness_values"],
                "confidence": aggregate["confidence"],
                "data_quality": "estimated",
                "fixture_hash": fixture["fixture_hash"],
                "status": aggregate["status"],
                "created_at": _stamp(self.clock()),
            }
            _validate_run(row)
            observation_rows = [
                {
                    "org_id": tenant,
                    "run_id": run_id,
                    "sequence": index,
                    "result_hash": item["result_hash"],
                    "output_hash": item["output_hash"],
                    "mentioned": item["mentioned"],
                    "citation_count": item["citation_count"],
                    "position": item["position"],
                    "correctness": item["correctness"],
                    "status": item["status"],
                }
                for index, item in enumerate(parsed, start=1)
            ]
            self.store.save_run(
                row,
                request_hash=request_hash,
                observations=observation_rows,
            )
            self.store.save_command(
                org_id=tenant,
                idempotency_key=key,
                request_hash=request_hash,
                response=row,
                fixture_version=int(fixture.get("version", 1)),
            )
            failed = row["status"] == "failed"
            self._audit(
                event_type="geo.run.manual_review" if failed else "geo.run.completed",
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=key,
                aggregate_id=run_id,
                input_hash=request_hash,
                output_hash=_hash(row),
                fixture_version=int(fixture.get("version", 1)),
                policy_hash=policy_hash,
                status=row["status"],
                reason="all unique samples require manual review" if failed else None,
                cost_cents=sum(max(0, int(item.get("cost_cents", 0))) for item in parsed),
            )
            return deepcopy(row)
        except GeoQueryFixtureError as error:
            public_error = error if isinstance(error, GeoRunError) else GeoRunError(
                error.code,
                str(error),
                details=getattr(error, "details", None),
            )
            self._reject(
                public_error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=audit_input_hash,
                fixture_version=audit_fixture_version,
                policy_hash=audit_policy_hash,
            )
            if public_error is error:
                raise
            raise public_error from error
        finally:
            self._lock.release()

    execute = run
    aggregate = run
    query = run
    collect = run
    parse = run

    def get_run(
        self,
        *,
        run_id: Any,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        identity = _uuid(run_id, "run_id")
        assert identity is not None
        row = self.store.get_run(org_id=tenant, run_id=identity)
        if row is None:
            if self.store.find_run(run_id=identity) is not None:
                raise GeoRunError("TENANT_SCOPE_VIOLATION", "run is outside this organization")
            raise GeoRunError("GEO_RUN_NOT_FOUND", "run does not belong to organization")
        return row

    get = get_run
    retrieve = get_run

    def list_runs(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> tuple[dict[str, Any], ...]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return self.store.list_runs(org_id=tenant)

    list = list_runs

    def audit_for(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return self.store.audit_for(org_id=tenant)


# Compatibility aliases for callers that use an explicit FakeGeo name.
FakeGeoService = GeoRunService
GeoContentRunService = GeoRunService
GeoRunStore = InMemoryGeoRunStore


__all__ = [
    "FakeGeoPort",
    "FakeGeo",
    "GeoRunError",
    "InMemoryGeoRunStore",
    "GeoRunStore",
    "GeoRunService",
    "FakeGeoService",
    "GeoContentRunService",
]
