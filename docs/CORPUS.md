# Reproduce the historical chart pairs

The optional corpus uses complete upstream charts fetched at verified digests.
The normal unit tests are offline and use synthetic controls. Upstream chart
sources, generated Secrets and raw renders are not included in the package.

Install the checker using the README, and have Helm 4.2.4 available. From a
source checkout:

```sh
python3 scripts/fetch_corpus.py --check
```

If your installed command is in a virtual environment outside PATH:

```sh
python3 scripts/fetch_corpus.py --check --checker .venv/bin/helm-hook-preflight
```

The script downloads to ignored `.corpus/`, checks every pinned input digest,
renders in memory and feeds the whole bundle to the checker through stdin.
Only JSON reports, source-download receipts and render hashes are saved.
Exit 1 or 2 from a chart check is an expected corpus observation, not a fetch
failure. The script itself exits nonzero for fetch, checksum, renderer or
checker-input failures. It does not install charts or contact Kubernetes.

Run the opt-in regression assertions after fetching:

```sh
HHP_CORPUS="$PWD/.corpus" python -m unittest discover -s tests -p test_corpus.py -v
```

| Fixture | Render profile | Expected bounded result |
|---|---|---|
| GreenKube v0.2.4 | release `screen`, namespace `probe`, `monitoring.serviceMonitor.enabled=true` | SA reference phase_mismatch, exit 1 |
| GreenKube v0.2.5 | same | Dedicated SA -15 before Job -10, ordered_before, exit 0 |
| DataHub 0.8.20 | release `screen`, namespace `probe`, default values | Three required auth Secret mismatches and one mysql unknown, exit 2 |
| DataHub 0.8.21 | same | Auth Secret -5 before Job -4; mysql still unknown, exit 2 |

DataHub has an earlier hook ServiceAccount as well; its supported report
therefore includes five references: one ServiceAccount, three auth Secret
occurrences and one MySQL Secret occurrence. The old auth Secret is main-phase;
the new one carries pre-install/pre-upgrade events. This command checks only
the pre-install model. It does not certify the Job image, RBAC, credentials,
Secret keys, database readiness or an installation.

The GreenKube source files are pinned to commits
`694f868dc1019dd08d246fc4cd14b7bb51c22661` and
`bc6d6229940f0858936b8cbb51a212cc730c1a3c`. DataHub uses official release
archives with SHA256 digests from the chart repository index. Exact URLs,
paths, digests, values and license links are in [tests/corpus.json](../tests/corpus.json).
Both upstream projects use Apache-2.0; see [NOTICE](../NOTICE).

Fresh render bytes are nondeterministic: both projects can generate Secret
data, and DataHub can generate bootstrap environment values. Pin source
checksums and compare resource identities, hook annotations and reference
paths, rather than expecting equal render hashes. Do not upload raw renders
to an issue. The report omits Secret payloads, but resource names and source
paths can still need sanitizing before sharing.

For the limitations of each baseline, read [BASELINE.md](BASELINE.md). The
historical upstream fixes establish a useful regression corpus. These
author/agent checks are not independent user trials.
