"""Account-free scheduler with UTC persistence and lease-based idempotency."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from threading import RLock
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SchedulerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError) as exc:
        raise SchedulerError("INVALID_SCHEDULER_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise SchedulerError("INVALID_SCHEDULER_COMMAND", f"{name} is required")
    return text


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchedulerError("INVALID_SCHEDULER_COMMAND", "timestamp must include a timezone")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class SchedulerJob:
    id: UUID
    org_id: UUID
    job_type: str
    schedule: str
    status: str
    created_at: str

    def as_contract(self) -> dict[str, str]:
        return {"id": str(self.id), "org_id": str(self.org_id), "job_type": self.job_type,
                "schedule": self.schedule, "status": self.status, "created_at": self.created_at}


@dataclass(frozen=True)
class ScheduleLease:
    job_id: UUID
    org_id: UUID
    worker_id: str
    occurrence_at: str
    lease_until: str
    claim_version: int
    region_profile_version_id: UUID


class SchedulerService:
    """Reference scheduler; a database adapter can persist the same transitions."""

    _INTERVAL = re.compile(r"^(?:interval:|@every\s+)(\d+)(?:s)?$")

    def __init__(self) -> None:
        self.jobs: dict[UUID, SchedulerJob] = {}
        self._state: dict[UUID, dict[str, Any]] = {}
        self._idempotency: dict[tuple[UUID, str], tuple[str, Any]] = {}
        self._completed: set[tuple[UUID, str]] = set()
        self._locks: dict[tuple[UUID, str], tuple[str, datetime]] = {}
        self._lock = RLock()

    def create_job(self, *, org_id: UUID | str, job_type: str, schedule: str,
                   region_profile_version_id: UUID | str, timezone_name: str = "UTC",
                   idempotency_key: str, now: datetime | None = None,
                   first_run_at: datetime | None = None) -> SchedulerJob:
        tenant = _uuid(org_id, "org_id")
        kind = _text(job_type, "job_type")
        expression = _text(schedule, "schedule")
        profile_version = _uuid(region_profile_version_id, "region_profile_version_id")
        zone = self._zone(timezone_name)
        key = _text(idempotency_key, "idempotency_key")
        current = _utc(now or datetime.now(timezone.utc))
        payload_hash = self._hash({"job_type": kind, "schedule": expression, "region_profile_version_id": str(profile_version), "timezone": zone.key})
        prior = self._idempotency.get((tenant, key))
        if prior is not None:
            if prior[0] != payload_hash:
                raise SchedulerError("IDEMPOTENCY_KEY_REUSED", "schedule idempotency key payload differs")
            return prior[1]
        next_at = _utc(first_run_at) if first_run_at is not None else self.next_run_at(expression, current, zone)
        created = SchedulerJob(uuid4(), tenant, kind, expression, "active", _stamp(current))
        self.jobs[created.id] = created
        self._state[created.id] = {"next_run_at": next_at, "timezone": zone.key,
                                   "region_profile_version_id": profile_version, "version": 0,
                                   "lease": None, "idempotency_key": key}
        self._idempotency[(tenant, key)] = (payload_hash, created)
        return created

    def pause(self, *, org_id: UUID | str, job_id: UUID | str, expected_version: int, idempotency_key: str) -> SchedulerJob:
        return self._set_status(org_id=org_id, job_id=job_id, expected_version=expected_version, idempotency_key=idempotency_key, status="paused")

    def resume(self, *, org_id: UUID | str, job_id: UUID | str, expected_version: int, idempotency_key: str, now: datetime | None = None) -> SchedulerJob:
        tenant = _uuid(org_id, "org_id")
        job = self._job(job_id, tenant)
        state = self._state[job.id]
        if state["version"] != expected_version:
            raise SchedulerError("VERSION_CONFLICT", "scheduler job version changed")
        if job.status != "paused":
            raise SchedulerError("INVALID_STATE_TRANSITION", "only paused jobs may resume")
        current = _utc(now or datetime.now(timezone.utc))
        state["next_run_at"] = self.next_run_at(job.schedule, current, self._zone(state["timezone"]))
        state["version"] += 1
        state["lease"] = None
        updated = replace(job, status="active")
        self.jobs[job.id] = updated
        self._remember_command(tenant, idempotency_key, {"job_id": str(job.id), "action": "resume", "version": expected_version}, updated)
        return updated

    def retire(self, *, org_id: UUID | str, job_id: UUID | str, expected_version: int, idempotency_key: str) -> SchedulerJob:
        return self._set_status(org_id=org_id, job_id=job_id, expected_version=expected_version, idempotency_key=idempotency_key, status="retired")

    def claim_due(self, *, org_id: UUID | str, worker_id: str, idempotency_key: str,
                  now: datetime | None = None, limit: int = 1, lease_seconds: int = 30) -> tuple[ScheduleLease, ...]:
        tenant = _uuid(org_id, "org_id")
        worker = _text(worker_id, "worker_id")
        key = _text(idempotency_key, "idempotency_key")
        if limit < 1 or lease_seconds < 1:
            raise SchedulerError("INVALID_SCHEDULER_COMMAND", "limit and lease_seconds must be positive")
        current = _utc(now or datetime.now(timezone.utc))
        command_hash = self._hash({"org_id": str(tenant), "worker_id": worker, "limit": limit})
        prior = self._idempotency.get((tenant, key))
        if prior is not None:
            if prior[0] != command_hash:
                raise SchedulerError("IDEMPOTENCY_KEY_REUSED", "claim idempotency key payload differs")
            return prior[1]
        leases: list[ScheduleLease] = []
        with self._lock:
            for job in sorted(self.jobs.values(), key=lambda item: str(item.id)):
                if len(leases) >= limit or job.org_id != tenant or job.status != "active":
                    continue
                state = self._state[job.id]
                due = state["next_run_at"]
                occurrence = _stamp(due)
                if due > current or (job.id, occurrence) in self._completed:
                    continue
                lock_key = (job.id, occurrence)
                existing_lock = self._locks.get(lock_key)
                if existing_lock is not None and existing_lock[1] > current:
                    continue
                until = current + timedelta(seconds=lease_seconds)
                self._locks[lock_key] = (worker, until)
                state["lease"] = (worker, occurrence, until)
                state["version"] += 1
                leases.append(ScheduleLease(job.id, tenant, worker, occurrence, _stamp(until), state["version"], state["region_profile_version_id"]))
        result = tuple(leases)
        self._idempotency[(tenant, key)] = (command_hash, result)
        return result

    def complete(self, *, org_id: UUID | str, lease: ScheduleLease, expected_version: int,
                 idempotency_key: str, now: datetime | None = None) -> SchedulerJob:
        tenant = _uuid(org_id, "org_id")
        job = self._job(lease.job_id, tenant)
        key = _text(idempotency_key, "idempotency_key")
        state = self._state[job.id]
        if state["version"] != expected_version:
            raise SchedulerError("VERSION_CONFLICT", "scheduler job version changed")
        held = state.get("lease")
        current = _utc(now or datetime.now(timezone.utc))
        if held is None or held[0] != lease.worker_id or held[1] != lease.occurrence_at:
            raise SchedulerError("LEASE_NOT_FOUND", "scheduler lease is not owned by worker")
        if held[2] <= current:
            raise SchedulerError("LEASE_EXPIRED", "scheduler lease has expired")
        self._completed.add((job.id, lease.occurrence_at))
        self._locks.pop((job.id, lease.occurrence_at), None)
        state["lease"] = None
        if job.schedule.lower() == "once":
            state["version"] += 1
            updated = replace(job, status="retired")
        else:
            state["next_run_at"] = self.next_run_at(job.schedule, current, self._zone(state["timezone"]))
            state["version"] += 1
            updated = job
        self.jobs[job.id] = updated
        self._remember_command(tenant, key, {"job_id": str(job.id), "action": "complete", "occurrence": lease.occurrence_at}, updated)
        return updated

    def next_run_at(self, schedule: str, after_utc: datetime, zone: ZoneInfo) -> datetime:
        expression = _text(schedule, "schedule")
        current = _utc(after_utc)
        if expression.lower() == "once":
            return current
        match = self._INTERVAL.fullmatch(expression.lower())
        if match:
            seconds = int(match.group(1))
            if seconds < 1:
                raise SchedulerError("INVALID_SCHEDULE", "interval must be positive")
            return current + timedelta(seconds=seconds)
        fields = expression.split()
        if len(fields) != 5:
            raise SchedulerError("INVALID_SCHEDULE", "schedule must be once, interval:N, @every N, or five-field UTC cron")
        local = current.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
        minimums = [0, 0, 1, 1, 0]
        maximums = [59, 23, 31, 12, 6]
        for _ in range(366 * 24 * 60):
            values = [local.minute, local.hour, local.day, local.month, (local.weekday() + 1) % 7]
            if all(self._cron_match(field, value, minimum, maximum) for field, value, minimum, maximum in zip(fields, values, minimums, maximums)):
                return local.replace(tzinfo=zone).astimezone(timezone.utc)
            local += timedelta(minutes=1)
        raise SchedulerError("INVALID_SCHEDULE", "cron schedule has no occurrence in the next year")

    @staticmethod
    def _cron_match(expression: str, value: int, minimum: int, maximum: int) -> bool:
        for part in expression.split(","):
            if part == "*":
                return True
            if part.startswith("*/"):
                step = int(part[2:])
                return step > 0 and (value - minimum) % step == 0
            if "-" in part:
                left, right = part.split("-", 1)
                if int(left) <= value <= int(right):
                    return True
            elif part.isdigit() and int(part) == value:
                return True
        return False

    def _set_status(self, *, org_id: UUID | str, job_id: UUID | str, expected_version: int, idempotency_key: str, status: str) -> SchedulerJob:
        tenant = _uuid(org_id, "org_id")
        job = self._job(job_id, tenant)
        state = self._state[job.id]
        if state["version"] != expected_version:
            raise SchedulerError("VERSION_CONFLICT", "scheduler job version changed")
        if status == "paused" and job.status != "active" or status == "retired" and job.status == "retired":
            raise SchedulerError("INVALID_STATE_TRANSITION", "scheduler job status cannot change")
        state["version"] += 1
        state["lease"] = None
        updated = replace(job, status=status)
        self.jobs[job.id] = updated
        self._remember_command(tenant, idempotency_key, {"job_id": str(job.id), "action": status, "version": expected_version}, updated)
        return updated

    def _remember_command(self, tenant: UUID, key: str, payload: Mapping[str, Any], result: Any) -> None:
        name = _text(key, "idempotency_key")
        digest = self._hash(payload)
        prior = self._idempotency.get((tenant, name))
        if prior is not None and prior[0] != digest:
            raise SchedulerError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
        self._idempotency[(tenant, name)] = (digest, result)

    def _job(self, job_id: UUID | str, tenant: UUID) -> SchedulerJob:
        identifier = _uuid(job_id, "job_id")
        job = self.jobs.get(identifier)
        if job is None:
            raise SchedulerError("JOB_NOT_FOUND", "scheduler job was not found")
        if job.org_id != tenant:
            raise SchedulerError("TENANT_SCOPE_VIOLATION", "scheduler job belongs to another organization")
        return job

    @staticmethod
    def _zone(name: str) -> ZoneInfo:
        try:
            return ZoneInfo(_text(name, "timezone_name"))
        except ZoneInfoNotFoundError as exc:
            raise SchedulerError("INVALID_SCHEDULER_COMMAND", "timezone_name must be an IANA timezone") from exc

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = ["ScheduleLease", "SchedulerError", "SchedulerJob", "SchedulerService"]
