# Supported contract

Schema `1.0`, CLI alpha `0.0.1a1`, Helm source oracle `4.2.4`. The input is a complete rendered native Helm bundle, UTF-8 file or stdin, explicit release namespace, and `--mode install`. Hooks must be enabled. This is a fresh first-install model, not upgrade/rollback/live-state analysis; a new Helm release does not imply an empty namespace.

Chart-declared provider identities are assumed not to preexist unless supplied in the external inventory. Other external resources may exist. Every consumer namespace, including an explicit namespace different from the release default, is assumed created and its default ServiceAccount controller reconciled before hooks. External actors must not mutate/delete dependencies during the hook group. The checker does not contact a cluster or execute hook commands.

## Identities and consumers

Only `batch/v1 Job` and `v1 Pod` with a top-level `helm.sh/hook` containing `pre-install` are consumers. Multiple recognized events are accepted. Other lifecycle events and resource kinds are listed in `out_of_scope`, including main workloads; their dependencies are not checked. Non-v1 target consumer APIs produce an unsupported result.

Provider identity is API group, kind, name, effective namespace. Matching supports core v1 ServiceAccount and Secret. Known namespaced resources fall back to the release namespace when namespace is omitted/empty. Known cluster-scoped objects do not receive it. API scope for unrelated custom resources is not guessed. Duplicate resource identities are rejected, including alternate API versions and main/hook duplicates. Cross-namespace objects never satisfy a Pod reference.

Each reference records consumer/provider identity, source file and document, optional Helm `# Source:` template path, hook events/weight/deletion policy, and exact field path. Reports exclude resource payloads, Secret keys/values, environment values, and container commands. Resource names/paths are not anonymized: sanitize them before sharing.

## References and coverage

- `serviceAccountName`, including implicit/empty/explicit `default`, is checked. Default SA yields `assumed_available`, based on controller reconciliation, not bundle membership or RBAC. Deprecated `serviceAccount` is explicitly unsupported.
- Ordinary and init containers: `env[].valueFrom.secretKeyRef` and `envFrom[].secretRef` are checked. `optional: true` is `not_required`; malformed optional values are input errors. Secret key existence and data suitability are never checked.
- ConfigMap env references; non-empty `imagePullSecrets`, `ephemeralContainers`, and `resourceClaims`; and volume sources other than `emptyDir`/`downwardAPI` are detected as unsupported. Projected sources are reported at their volume path. Their presence makes the report incomplete.
- Other Pod/Kubernetes fields are not exhaustively traversed or schema validated. Downward API selectors do not create resource dependencies. Arbitrary operators, API references, RBAC permissions, network/readiness/image behavior, commands, migrations, and application cycles are outside scope.

An implicit default SA is itself a reference result. A bundle with no target references reports `not_applicable`, counts, and explicit limits; it is not a chart-wide pass. Coverage counts unsupported reference-family markers as reference results, not individual Kubernetes references hidden inside them.

## Per-reference states

| State | Meaning |
|---|---|
| `ordered_before` | Matching pre-install provider has a strictly lower weight |
| `phase_mismatch` | Matching provider is main-phase, has no pre-install event, or has a higher pre-install weight |
| `external_or_unknown` | No matching provider, or equal-weight ordering was not modeled |
| `unsupported` | Detected reference family or target API outside the supported analysis |
| `not_required` | Optional Secret presence is not required |
| `declared_external` | Inventory asserts this identity exists before hooks; not live verified |
| `assumed_available` | Default ServiceAccount availability is a namespace/controller assumption |

Inventory takes precedence over bundle ordering for required references. Input is identity-only YAML documents, each with only `apiVersion: v1`, `kind: Secret` or `ServiceAccount`, and `metadata.name` plus optional `metadata.namespace`. It accepts no annotations, payloads, or key assertions. See `examples/external-inventory.yaml`.

## Helm oracle and strict input restrictions

[hooks.go at v4.2.4](https://github.com/helm/helm/blob/v4.2.4/pkg/action/hooks.go) orders selected hooks by weight, then name, using a stable sort after earlier manifest kind ordering. This alpha deliberately leaves all equal weights unknown instead of implementing an unproven shortcut. Successful hook cleanup iterates after the whole event group, so an earlier GreenKube SA with `hook-succeeded` does not disappear before its Job. Failed hooks and external mutations are not simulated. Ordinary resources are created after pre-install execution in [install.go](https://github.com/helm/helm/blob/v4.2.4/pkg/action/install.go).

Helm parses hook annotations on the top-level document before Kubernetes List flattening. This alpha rejects all `List` wrappers instead of misclassifying item annotations. Expand manifests at the rendering source; flattening a List yourself can change Helm lifecycle semantics.

YAML aliases/merge keys, duplicate keys, non-string mapping keys, malformed timestamps, empty-only bundles, malformed relevant structures/annotations, unrecognized or duplicate hook events, and invalid/overflow weights are controlled input errors. Empty documents between resources are ignored. Hook tokens must use canonical lowercase spellings. This is stricter than Helm, which lowercases tokens and can ignore unknown hook events or coerce invalid weights to zero. Strict rejection avoids a misleading analyzed result. Limits: 16 MiB UTF-8, 10,000 documents, 500,000 YAML events, 80 nesting levels.

Optional null collections/selector pointers follow Kubernetes absence semantics: null env, envFrom, initContainers, volumes and other optional collections are empty; null optional Secret boolean means required; null annotations are empty; null ServiceAccount name defaults. `valueFrom: null` is absent; a Secret selector can accompany an empty/null `value`, but not a nonempty value. Inactive null selectors do not count as competing selectors. Required containers remain nonempty. Parser diagnostics omit YAML values and do not emit tracebacks for recognized input failures. Unexpected programming errors are not swallowed. JSON uses schema versioning; enum additions within a future schema are not promised backwards compatible without release notes.

## Summary and exit priority

`violations`, `unknown`, `unsupported`, `incomplete`, `verdict_counts`, coverage, model and assumptions coexist. Exit priority: input/config error 3; unknown/unsupported 2; violation without incomplete 1; otherwise 0. Mixed violation+unknown retains every finding and returns 2. On input error, `analysis_performed` is false, findings are empty, and zero counts are not a statement about the bundle.

The check assumes ordinary native Helm execution, not Argo CD event mapping, `--no-hooks`, operators, prior release history, custom deletion controllers, or all Helm versions. Existence earlier in the declaration sequence is not evidence of application success.
