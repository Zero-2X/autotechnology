# packages/prompt_registry

`EvaluationService` registers tenant-scoped immutable Prompt, synthetic golden-set, and regression-threshold versions. Offline runs use the existing `ModelGateway`, retain per-case hashes and cost evidence, and compare candidate runs with an optional baseline.

The service stores no provider credential and makes no direct network call. EvalRun evidence excludes prompt inputs, expected values, and model output bodies; Fake Provider remains the CI path.
