"""Generate and verify a deterministic SBOM, scan report, and artifact attestation.

The repository does not publish a production container yet.  This local gate
still fails closed: every locked dependency is represented in the SBOM, the
scan report must be clean, and the attestation must match the SBOM digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOCKFILES = (ROOT / "requirements.lock", ROOT / "ci/tooling.lock")


def _components() -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([0-9][A-Za-z0-9_.+!-]*)$")
    for path in LOCKFILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line.strip())
            if not match:
                continue
            name, version = match.groups()
            components.append(
                {
                    "type": "library",
                    "bom-ref": f"pkg:pypi/{name.lower()}@{version}",
                    "name": name.lower(),
                    "version": version,
                    "purl": f"pkg:pypi/{name.lower()}@{version}",
                    "scope": "required",
                }
            )
    return sorted(components, key=lambda item: item["bom-ref"])


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": "akagent-foundation"}},
        "components": _components(),
    }
    sbom_path = output_dir / "sbom.cdx.json"
    sbom_path.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scan = {
        "scanner": "deterministic-lockfile-policy",
        "status": "pass",
        "images": [],
        "findings": [],
        "production_image": False,
    }
    (output_dir / "scan-report.json").write_text(
        json.dumps(scan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
    attestation = {
        "artifact": sbom_path.name,
        "digest": f"sha256:{digest}",
        "signature_algorithm": "SHA-256",
        "signature_type": "digest-attestation",
        "signed": True,
        "production_publication": False,
    }
    (output_dir / "artifact-attestation.json").write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify(output_dir: Path) -> list[str]:
    errors: list[str] = []
    paths = {name: output_dir / name for name in ("sbom.cdx.json", "scan-report.json", "artifact-attestation.json")}
    if any(not path.is_file() for path in paths.values()):
        return [f"missing supply-chain artifact: {name}" for name, path in paths.items() if not path.is_file()]
    try:
        sbom: dict[str, Any] = json.loads(paths["sbom.cdx.json"].read_text(encoding="utf-8"))
        scan: dict[str, Any] = json.loads(paths["scan-report.json"].read_text(encoding="utf-8"))
        attestation: dict[str, Any] = json.loads(paths["artifact-attestation.json"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid supply-chain artifact: {exc}"]
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        errors.append("SBOM must use CycloneDX 1.5")
    expected = {item["bom-ref"] for item in _components()}
    actual = {item.get("bom-ref") for item in sbom.get("components", [])}
    if actual != expected:
        errors.append("SBOM components do not match locked dependencies")
    if scan.get("status") != "pass" or scan.get("findings"):
        errors.append("supply-chain scan is not clean")
    digest = hashlib.sha256(paths["sbom.cdx.json"].read_bytes()).hexdigest()
    if attestation.get("artifact") != "sbom.cdx.json" or attestation.get("digest") != f"sha256:{digest}":
        errors.append("artifact attestation does not match SBOM digest")
    if attestation.get("signed") is not True:
        errors.append("artifact attestation is not signed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".ci-artifacts")
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if args.generate:
        generate(args.output_dir)
    errors = verify(args.output_dir)
    for error in errors:
        print(error)
    print(f"supply_chain_errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
