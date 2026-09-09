# Try one chart task

Pick a chart where you are changing a pre-install hook, ServiceAccount, or required Secret reference before its next first-install release. Use your existing render with the actual values profile and namespace, then run the README command. Do not install a historical example into a cluster for this trial.

Record the check result, a surprising or incorrect reference, and whether you could explain the consumer/provider order from the report. If a provider is external, review the prerequisite before asserting its identity in an inventory. Share sanitized identities/annotations and the tool/Helm versions, never Secret values or a private full render.

Compare the same task with your current method: a short phase-aware script or a chart-specific helm-unittest assertion. Record setup time, commands needed, explanation quality, and a decision you made. A clear result can be useful without finding a new defect. The question is whether reusable diagnostics reduce work for your task.

Feedback fields: actual task and chart revision; author help received; install/check completed; result understood; correction or decision; next eligible first-install/release; whether you used it again. Self-run examples, CI downloads, and model review do not count as external trials. [Open feedback](https://github.com/ruslan-shaydullin/helm-hook-preflight/issues/new?template=feedback.yml).
