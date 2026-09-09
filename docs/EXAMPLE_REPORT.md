# Versioned JSON report

Generated from `examples/bad.yaml` with namespace `demo` and `--mode install --format json`. This excerpt retains the summary, coverage and complete reference result. The full output also includes assumptions, external inventory, out-of-scope resources and errors. [Complete output](../examples/bad-report.json).

```json
{
  "schema_version": "1.0",
  "tool_version": "0.0.1a1",
  "model": "fresh_first_install",
  "helm_semantics_version": "4.2.4",
  "namespace": "demo",
  "summary": {
    "status": "violations",
    "exit_code": 1,
    "violations": 1,
    "unknown": 0,
    "unsupported": 0,
    "incomplete": false,
    "analysis_performed": true,
    "verdict_counts": {
      "phase_mismatch": 1
    }
  },
  "coverage": {
    "resources": 2,
    "consumers": 1,
    "references": 1,
    "out_of_scope_resources": 1,
    "supported_reference_families": [
      "serviceAccountName (including implicit default)",
      "env.valueFrom.secretKeyRef",
      "envFrom.secretRef"
    ],
    "supported_containers": [
      "containers",
      "initContainers"
    ],
    "limits": [
      "Only batch/v1 Job and v1 Pod pre-install consumers.",
      "Unsupported detected reference families make the report incomplete.",
      "Other Kubernetes fields, hook kinds, and lifecycle events are not validated.",
      "Not a Kubernetes schema validator; not a full chart or deployment verdict."
    ]
  },
  "findings": [
    {
      "consumer": {
        "identity": {
          "group": "batch",
          "kind": "Job",
          "name": "migration",
          "namespace": "demo"
        },
        "api_version": "batch/v1",
        "events": [
          "pre-install"
        ],
        "phase": "hook",
        "weight": -4,
        "delete_policies": [
          "before-hook-creation"
        ],
        "source": {
          "file": "examples/bad.yaml",
          "document": 1,
          "line": 2
        }
      },
      "dependency": {
        "group": "",
        "kind": "ServiceAccount",
        "name": "runner",
        "namespace": "demo"
      },
      "provider": {
        "identity": {
          "group": "",
          "kind": "ServiceAccount",
          "name": "runner",
          "namespace": "demo"
        },
        "api_version": "v1",
        "events": [],
        "phase": "main",
        "weight": null,
        "delete_policies": [],
        "source": {
          "file": "examples/bad.yaml",
          "document": 2,
          "line": 18
        }
      },
      "reference_path": "spec.template.spec.serviceAccountName",
      "required": true,
      "verdict": "phase_mismatch",
      "reason": "provider_main_phase",
      "explanation": "Dependency is declared in the main phase, after the blocking pre-install hook."
    }
  ]
}
```

A missing provider is `external_or_unknown`, not proven cluster absence. An inventory match is `declared_external`, not live verification. With both a violation and an unknown, exit 2 takes precedence but both reference results and both counts remain. Input errors use the same schema envelope, `errors`, `summary.status: input_error`, exit 3 and `analysis_performed: false`; no partial findings are claimed.
