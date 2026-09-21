# packages/testkit

Fixtures, fake clock and replay helpers shared by tests; no production business facts.

`create_synthetic_fixture(seed)` returns deterministic tenant/correlation IDs,
an explicit UTC `FakeClock`, an isolated private `FakeStorage`, and append-only
audit facts that contain object references and hashes rather than payload bytes.
The same seed and start time reproduce the same contract snapshot.

This directory is a V2 boundary created by FOUND-001. Add implementation only under the owning task card and preserve the synthetic/account-free constraints.
