# helm-hook-preflight

Catch a direct Helm hook dependency declared too late for a **fresh first install**, using a complete rendered YAML bundle. No Kubernetes access, Helm runtime dependency, or telemetry.

A pre-install Job can reference a ServiceAccount that the chart creates in the main phase. A required Secret environment reference has a similar problem: the container waits for the Secret while Helm waits for the Job before creating main resources. This alpha reports the consumer, dependency, namespace, field, phase, and reason under explicit install assumptions.

## Install and try

Python 3.10–3.14. Install the alpha wheel from the [GitHub release](https://github.com/ruslan-shaydullin/helm-hook-preflight/releases/tag/v0.0.1a1); this release is not published on PyPI.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install 'https://github.com/ruslan-shaydullin/helm-hook-preflight/releases/download/v0.0.1a1/helm_hook_preflight-0.0.1a1-py3-none-any.whl'
helm template demo ./chart --namespace demo > rendered.yaml
.venv/bin/helm-hook-preflight check rendered.yaml --namespace demo --mode install --format json
```

The `helm template` command is an external render step. Use the complete bundle and the same values/namespace intended for first install. Do not use `--no-hooks`. `--mode install` explicitly selects the fresh first-install assumptions; upgrades and GitOps hook remapping are unsupported.

From a checkout, try the synthetic examples (do not deploy them):

```sh
.venv/bin/helm-hook-preflight check examples/bad.yaml --namespace demo --mode install
# exit 1: ServiceAccount/runner is declared in the main phase
.venv/bin/helm-hook-preflight check examples/good.yaml --namespace demo --mode install
# exit 0: ServiceAccount/runner has lower pre-install weight
.venv/bin/helm-hook-preflight check examples/unknown.yaml --namespace demo --mode install
# exit 2: provider absent from bundle; external existence unknown
```

For example, `batch/v1 Job demo/migration` at weight `-4` referencing `v1 ServiceAccount demo/runner`:

| Provider declaration | Result |
|---|---|
| Main phase | `phase_mismatch`: provider is declared after the blocking hook |
| Pre-install, weight -5 | `ordered_before`: provider creation precedes the consumer |
| Missing from bundle | `external_or_unknown`: cluster existence was not inspected |
| Pre-install, weight -4 | `external_or_unknown`: equal weights intentionally not modeled |

## Read the result

| Exit | Meaning within this check |
|---|---|
| 0 | No violations or incomplete reference results; may be `not_applicable` if there are no target consumers |
| 1 | Declared order violations, without incomplete results |
| 2 | Unknown or unsupported references; any violations remain in the report |
| 3 | Input/configuration error; analysis was not performed |

Supported consumers: `batch/v1 Job` and `v1 Pod` pre-install hooks. Supported references: ServiceAccount name, `env.valueFrom.secretKeyRef`, and `envFrom.secretRef` in ordinary/init containers. Optional Secret references are reported as `not_required`. The default ServiceAccount is an explicit controller assumption. An identity-only `--external-inventory` can assert a preexisting Secret or ServiceAccount; it is never live verification.

**An earlier provider does not prove readiness, Secret contents/keys, RBAC permissions, image compatibility, or successful installation.** Main-phase violations assume chart-declared identities do not already exist unless asserted in the inventory. Other external resources may already exist in a new release's namespace. Known unsupported reference families in target consumers make the result incomplete. Other hook kinds/events are counted outside consumer scope.

See [scope and assumptions](docs/SCOPE.md), [JSON example](docs/EXAMPLE_REPORT.md), [CI integration](docs/CI.md), [validation](docs/VALIDATION.md), and [historical demo](docs/DEMO.md). Helm semantics are pinned to **4.2.4**; support is not inferred for all Helm 3/4 versions.

## Evidence and alternatives

Historical GreenKube v0.2.4→v0.2.5 changes a main-phase SA reference to an earlier hook SA. DataHub chart 0.8.20→0.8.21 orders the auth Secret references, while `mysql-secrets` remains unknown. These are static render regressions, not cluster install measurements. The corpus is fetched from pinned public sources; raw upstream renders and Secret values are not committed.

Helm lint, a selected KubeLinter SA-existence rule, phase-aware scripts, and chart-specific helm-unittest assertions were compared. Scripts and helm-unittest can catch these known regressions. The reusable contract and diagnostic workflow are the product hypothesis; user benefit over those alternatives is not yet measured. [Baseline](docs/BASELINE.md).

## Feedback and development

Try a chart you are changing and report a wrong finding, an unknown you cannot resolve, or an installation obstacle through [issues](https://github.com/ruslan-shaydullin/helm-hook-preflight/issues). Include sanitized identities and relevant annotations; do not attach Secret values. [Pilot task](docs/PILOT.md).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e . build
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m build
```

MIT licensed. See [contributing](CONTRIBUTING.md) and [upstream provenance](NOTICE).
