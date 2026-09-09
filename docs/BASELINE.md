# What this adds to existing checks

This alpha packages a narrow Helm creation-order contract, occurrence-level
diagnostics, conservative unknowns and regression controls. The underlying
comparison is simple. A small script or chart-specific helm-unittest assertions
may be sufficient for your workflow; independent usability benefit remains
unmeasured.

The following runs were repeated on 9 September 2026 with Helm 4.2.4,
KubeLinter 0.8.3, helm-unittest 1.1.2 and the historical chart inputs described
in [CORPUS.md](CORPUS.md). No chart was installed in a Kubernetes cluster.

| Historical inputs | Helm lint | KubeLinter | Short phase script | Authored helm-unittest assertion | This alpha |
|---|---|---|---|---|---|
| GreenKube v0.2.4 → v0.2.5, serviceMonitor enabled | Exit 0 → 0 | Selected `non-existent-service-account`: 0 → 0 findings | Main-phase account → earlier hook account | Exit 1 → 0 | Required SA mismatch → ordered_before; exits 1 → 0 |
| DataHub 0.8.20 → 0.8.21, default values | Exit 0 → 0 | All built-in rules: 199 → 201 other findings, exit 1 both | Three auth refs move main → earlier pre-install; mysql remains unknown | Auth Secret phase expectation: exit 1 → 0 | Three auth mismatches → ordered_before; mysql remains unknown; exits 2 → 2 |

GreenKube's fixed chart points the CRD-check Job at a dedicated hook
ServiceAccount with weight -15 before the Job at -10. The correction also
contains RBAC changes which this checker does not validate. See the
[historical upstream comparison](https://github.com/GreenKubeCloud/GreenKube/compare/v0.2.4...v0.2.5).

DataHub moves its auth Secret to pre-install at weight -5 before system-update
at -4. One Secret supplies three direct environment-variable references.
The required `mysql-secrets` reference remains unresolved in both bundles.
See [upstream PR 674](https://github.com/acryldata/datahub-helm/pull/674).
The fixed auth relationship does not establish a successful installation.

The [released KubeLinter SA rule](https://github.com/stackrox/kube-linter/blob/v0.8.3/pkg/templates/nonexistentserviceaccount/template.go)
matches ServiceAccount namespace/name without Helm lifecycle ordering. This
explains the selected GreenKube result; it is not a claim that all linters
pass DataHub or that KubeLinter is ineffective.

[helm-unittest](https://github.com/helm-unittest/helm-unittest/tree/v1.1.2)
was actually executed with chart-specific expectations: GreenKube's Job uses
the dedicated hook account, and DataHub's auth Secret carries pre-install/-5
annotations. Those tests distinguish the known corrections too. A maintained
expectation can be the better solution when a chart owner already knows the
relationship to protect.

[chart-testing](https://github.com/helm/chart-testing/tree/v3.14.0) supplies
install workflows, and [Nelm](https://github.com/werf/nelm) already has
[direct dependency extraction](https://github.com/werf/nelm/blob/f2302db9de49a0600d41fdf9542f8773c071f5d8/pkg/resource/dependency.go),
including optional references. Their documentation/source were reviewed;
their install/plan behavior on these charts was not executed. No claim is
made that Nelm would miss these cases. An upstream KubeLinter rule or shared
corpus remains a credible future direction.

The next useful comparison is a maintainer's real new chart/values task:
compare setup, actionable references, unknowns and time to understand the
result against their existing script or assertions. Local test runs, old
merged fixes and model review do not establish user demand.
