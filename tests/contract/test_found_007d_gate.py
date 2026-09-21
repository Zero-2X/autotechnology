from types import SimpleNamespace

from scripts import check_foundation_contracts as gate


def test_gate_stops_when_frontend_tools_are_missing(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda tool: None)
    calls = []
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: calls.append(a))
    assert gate.main() == 1
    assert calls == []


def test_gate_stops_at_first_failed_check(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda tool: tool)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["cwd"] == gate.ROOT
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=7)
    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 7
    assert len(calls) == 1


def test_gate_runs_full_suite_after_checks(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda tool: tool)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.main() == 0
    assert len(calls) == len(gate.CHECKS)
    assert calls[-1][1:4] == ["-m", "pytest", "tests"]
