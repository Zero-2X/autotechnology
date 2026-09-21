from __future__ import annotations

from pathlib import Path
import json

from jsonschema import Draft202012Validator

from scripts.check_architecture import check_architecture, load_policy
from scripts.smoke_foundation import main as smoke_main


ROOT = Path(__file__).resolve().parents[2]


def test_architecture_policy_contract_and_current_tree() -> None:
    policy = load_policy()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/architecture-guard.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/foundation.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(policy)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./architecture-guard.schema.json"}
    assert check_architecture() == []


def test_checker_rejects_lateral_import_and_cross_module_write(tmp_path: Path) -> None:
    topic = tmp_path / "modules/topic"
    topic.mkdir(parents=True)
    (topic / "service.py").write_text(
        "from modules.governance.repository import PolicyRepository\n"
        "from modules import distribution\n"
        "import infra.foundation.database\n"
        "query = 'UPDATE policy_versions SET status = 1'\n",
        encoding="utf-8",
    )
    errors = check_architecture(tmp_path, load_policy())
    assert any("cross_module_import:governance" in error for error in errors)
    assert any("cross_module_import:distribution" in error for error in errors)
    assert any("domain_imports_infra" in error for error in errors)
    assert any("cross_module_write:policy_versions" in error for error in errors)


def test_checker_rejects_app_direct_write_and_dynamic_import(tmp_path: Path) -> None:
    api = tmp_path / "apps/api"
    api.mkdir(parents=True)
    (api / "main.py").write_text("query = 'DELETE FROM task_jobs WHERE id = 1'\n", encoding="utf-8")
    topic = tmp_path / "modules/topic"
    topic.mkdir(parents=True)
    (topic / "service.py").write_text("other = __import__('modules.governance.private')\n", encoding="utf-8")
    errors = check_architecture(tmp_path, load_policy())
    assert any("app_direct_write:task_jobs" in error for error in errors)
    assert any("cross_module_import:governance" in error for error in errors)


def test_offline_smoke_checks_api_and_shared_storage_tenancy() -> None:
    assert smoke_main() == 0
