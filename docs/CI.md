# CI after rendering

Use Python 3.10–3.14 and the wheel in the pinned alpha release. Place this after your existing successful full `helm template` step, using its namespace and values. Preserve exit codes 1/2/3 and save the report even when the check fails.

```yaml
- name: Check rendered hooks
  run: |
    helm-hook-preflight check rendered.yaml --namespace demo --mode install --format json > hook-report.json
- name: Save hook report
  if: always()
  uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
  with:
    name: hook-report
    path: hook-report.json
    if-no-files-found: warn
```

The checker writes JSON to stdout, and an additional payload-free input-error diagnostic to stderr for exit 3. GitHub retains stderr in the step log. Do not use `|| true` or `continue-on-error` to turn an incomplete result into a pass. Avoid a pipeline that replaces the checker's exit code; use `set -o pipefail` if you introduce one.

No raw renders are uploaded by this recipe. Reports omit Secret contents but include resource names and source paths; apply your project's retention/access policy. An unsupported reference is a request for separate review, not automatically a chart defect. Use the identity-only inventory only for real, explicit install prerequisites.

This repository's CI tests Python 3.10 and 3.14, builds wheel/sdist, installs both outside the source tree, and verifies all four exit codes. Actions are pinned to verified revisions with `contents: read` only. Historical corpus fetching is an optional explicit network step; default tests are offline.
