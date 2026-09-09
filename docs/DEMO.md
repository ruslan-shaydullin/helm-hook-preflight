# Reproduce two historical fixes

These are historical, already fixed upstream relationships. No chart install or runtime failure is simulated. Helm **4.2.4** and the installed checker are required for this optional networked demo; normal CLI use needs only Python and PyYAML.

From this repository checkout:

```sh
.venv/bin/python scripts/fetch_corpus.py --check --checker .venv/bin/helm-hook-preflight
HHP_CORPUS="$PWD/.corpus" .venv/bin/python -m unittest discover -s tests -v
```

The script downloads pinned source files/archives, verifies SHA256, renders the complete charts in memory with `helm template screen CHART --namespace probe`, and pipes each bundle to `helm-hook-preflight check - --namespace probe --mode install --format json`. GreenKube also uses `--set monitoring.serviceMonitor.enabled=true`. It writes only diagnostic JSON and hash receipts under ignored `.corpus/reports`; generated Secret values are neither printed nor saved as renders.

| Historical input | Expected reference results | Exit |
|---|---|---|
| GreenKube v0.2.4 | `screen-greenkube-crd-check` Job, weight -10, uses main-phase `screen-greenkube` SA: `phase_mismatch` | 1 |
| GreenKube v0.2.5 | Same consumer/field uses dedicated hook `screen-greenkube-crd-check` SA at -15: `ordered_before` | 0 |
| DataHub 0.8.20 | Three env references to `datahub-auth-secrets` are `phase_mismatch`; `mysql-secrets` remains `external_or_unknown` | 2 |
| DataHub 0.8.21 | Same three auth refs are `ordered_before` (-5 provider before -4 Job); `mysql-secrets` remains `external_or_unknown` | 2 |

The fixed GreenKube result covers one SA-order reference only; the accompanying RBAC fix and CRD checks are not validated. DataHub's five results include an earlier SA in both versions. Its fixed auth references do not establish a successful full installation.

Inspect `.corpus/reports/datahub-0.8.21.json`: `summary.violations` is 0, `summary.unknown` is 1, and `summary.exit_code` is 2. `findings` identifies each reference and its reason. A small independent script or chart-specific helm-unittest assertion can catch these known relationships too; see [baseline](BASELINE.md).

Do not automatically move every dependency into a hook. Depending on the chart's intended lifecycle, a maintainer could declare a dedicated earlier hook provider, require and document an external prerequisite, or restructure when the consumer runs. Review ownership, cleanup, permissions and upgrade behavior independently.

Sources: [GreenKube comparison](https://github.com/GreenKubeCloud/GreenKube/compare/v0.2.4...v0.2.5), [DataHub PR #674](https://github.com/acryldata/datahub-helm/pull/674), and [digest-pinned corpus manifest](../tests/corpus.json). See [provenance and licensing](CORPUS.md).
