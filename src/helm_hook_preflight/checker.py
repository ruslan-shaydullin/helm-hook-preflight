"""Pure creation-order analysis for the explicitly bounded install model."""
from collections import Counter

from . import __version__
from .model import Identity, InputError, Resource
from .parser import mapping, sequence, string

SCHEMA_VERSION = "1.0"
HELM_VERSION = "4.2.4"
ASSUMPTIONS = [
    "Complete rendered bundle for a fresh native Helm first install; hooks enabled.",
    "Chart-declared dependencies do not preexist unless listed in the identity-only external inventory.",
    "Every consumer namespace (explicit or release default) exists before hooks and its default ServiceAccount controller has reconciled.",
    "An earlier declaration proves only creation order, not readiness, Secret keys, RBAC, images, or install success.",
    "No external actor mutates or deletes dependencies during the hook group.",
]


def base_report(namespace: str | None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION, "tool_version": __version__,
        "model": "fresh_first_install", "helm_semantics_version": HELM_VERSION,
        "namespace": namespace, "assumptions": list(ASSUMPTIONS),
        "findings": [], "out_of_scope": [], "errors": [],
    }


def error_report(error: InputError, namespace: str | None) -> dict:
    report = base_report(namespace)
    report["errors"] = [{"code": error.code, "message": str(error)}]
    report["summary"] = {"status": "input_error", "exit_code": 3, "violations": 0,
                         "unknown": 0, "unsupported": 0, "incomplete": True,
                         "analysis_performed": False}
    report["coverage"] = {"analysis_performed": False}
    return report


def verdict(consumer: Resource, provider: Resource | None, dependency: Identity,
            required: bool, external: set[Identity]) -> tuple[str, str, str]:
    if not required:
        return "not_required", "optional_secret", "Optional Secret reference does not require provider presence; contents are not checked."
    if dependency in external:
        return "declared_external", "inventory_assertion", "Identity is asserted to exist before hooks by external inventory; not live verified."
    if dependency.kind == "ServiceAccount" and dependency.name == "default":
        return "assumed_available", "default_service_account", "Availability is assumed from namespace/default ServiceAccount controller reconciliation; RBAC is not checked."
    if provider is None:
        return "external_or_unknown", "provider_not_in_bundle", "No matching provider in this bundle; external existence is unknown."
    if provider.api_version != "v1":
        return "unsupported", "provider_api_version", "Provider API version is outside the v1 Secret/ServiceAccount contract."
    if not provider.events:
        return "phase_mismatch", "provider_main_phase", "Dependency is declared in the main phase, after the blocking pre-install hook."
    if "pre-install" not in provider.events:
        return "phase_mismatch", "provider_not_pre_install", "Dependency has no pre-install event and is not created before this consumer under the first-install assumptions."
    if provider.weight < consumer.weight:
        return "ordered_before", "lower_hook_weight", "Dependency has a lower pre-install weight; hook-succeeded cleanup follows the complete hook group."
    if provider.weight > consumer.weight:
        return "phase_mismatch", "higher_hook_weight", "Dependency has a higher pre-install weight and is created after this blocking hook."
    return "external_or_unknown", "equal_weight_not_modeled", "Equal-weight tie ordering is intentionally not modeled by this alpha."


def analyze(resources: list[Resource], namespace: str, external: set[Identity] | None = None) -> dict:
    external = external or set()
    providers = {r.identity: r for r in resources if r.identity.group == "" and r.identity.kind in ("Secret", "ServiceAccount")}
    report = base_report(namespace)
    report["external_inventory"] = [i.report() for i in sorted(external, key=lambda i: (i.kind, i.namespace or "", i.name))]
    findings, consumers = report["findings"], 0

    def add(consumer, path, kind, name, required=True):
        dependency = Identity("", kind, name, consumer.identity.namespace)
        provider = providers.get(dependency)
        status, reason, explanation = verdict(consumer, provider, dependency, required, external)
        findings.append({"consumer": consumer.report(), "dependency": dependency.report(),
                         "provider": provider.report() if provider else None,
                         "reference_path": path, "required": required,
                         "verdict": status, "reason": reason, "explanation": explanation})

    def unsupported(consumer, path, reason):
        findings.append({"consumer": consumer.report(), "dependency": None, "provider": None,
                         "reference_path": path, "required": None, "verdict": "unsupported",
                         "reason": reason, "explanation": "This reference family is outside the supported check; review it separately."})

    def secret_ref(consumer, value, path, key_required):
        ref = mapping(value, path)
        name = string(ref.get("name"), path + ".name")
        if key_required:
            string(ref.get("key"), path + ".key")
        optional = ref.get("optional", False)
        if optional is None:
            optional = False  # A nullable Kubernetes *bool is unspecified.
        if type(optional) is not bool:
            raise InputError("optional_type", f"Expected boolean optional at {path}.optional.")
        add(consumer, path, "Secret", name, not optional)

    for consumer in resources:
        if "pre-install" not in consumer.events:
            report["out_of_scope"].append({"resource": consumer.report(), "reason": "not_a_pre_install_consumer"})
            continue
        ident = consumer.identity
        if (ident.group, ident.kind) not in (("batch", "Job"), ("", "Pod")):
            report["out_of_scope"].append({"resource": consumer.report(), "reason": "hook_kind_outside_consumer_scope"})
            continue
        if consumer.api_version != ("batch/v1" if ident.kind == "Job" else "v1"):
            unsupported(consumer, "apiVersion", "consumer_api_version")
            continue
        consumers += 1
        pod = mapping(consumer.body.get("spec"), "spec")
        prefix = "spec"
        if ident.kind == "Job":
            pod = mapping(mapping(pod.get("template"), "spec.template").get("spec"), "spec.template.spec")
            prefix = "spec.template.spec"
        if "serviceAccount" in pod:
            unsupported(consumer, prefix + ".serviceAccount", "deprecated_service_account_alias")
        if "serviceAccountName" in pod:
            name = string("" if pod["serviceAccountName"] is None else pod["serviceAccountName"], prefix + ".serviceAccountName", empty=True)
            add(consumer, prefix + ".serviceAccountName", "ServiceAccount", name or "default")
        elif "serviceAccount" not in pod:
            add(consumer, prefix + ".serviceAccountName", "ServiceAccount", "default")
        containers = sequence(pod.get("containers"), prefix + ".containers")
        if not containers:
            raise InputError("empty_containers", "Supported hook PodSpec must have a nonempty containers list.")
        for family in ("containers", "initContainers"):
            raw_containers = pod.get(family)
            for ci, item in enumerate(sequence([] if raw_containers is None else raw_containers, prefix + "." + family)):
                cp = f"{prefix}.{family}[{ci}]"
                container = mapping(item, cp)
                string(container.get("name"), cp + ".name")
                for ei, item in enumerate(sequence([] if container.get("env") is None else container["env"], cp + ".env")):
                    ep = f"{cp}.env[{ei}]"
                    env = mapping(item, ep)
                    string(env.get("name"), ep + ".name")
                    if env.get("valueFrom") is None:
                        continue
                    value = mapping(env["valueFrom"], ep + ".valueFrom")
                    known = {"secretKeyRef", "configMapKeyRef", "fieldRef", "resourceFieldRef"}
                    if not set(value).issubset(known):
                        raise InputError("env_value_from", "env.valueFrom contains an unknown selector.")
                    value = {key: selector for key, selector in value.items() if selector is not None}
                    if len(value) != 1 or env.get("value") not in (None, ""):
                        raise InputError("env_value_from", "env.valueFrom must contain exactly one active selector and cannot accompany a nonempty value.")
                    if "secretKeyRef" in value:
                        secret_ref(consumer, value["secretKeyRef"], ep + ".valueFrom.secretKeyRef", True)
                    elif "configMapKeyRef" in value:
                        unsupported(consumer, ep + ".valueFrom.configMapKeyRef", "config_map_reference")
                for ei, item in enumerate(sequence([] if container.get("envFrom") is None else container["envFrom"], cp + ".envFrom")):
                    ep = f"{cp}.envFrom[{ei}]"
                    value = mapping(item, ep)
                    if not (set(value) - {"prefix"}).issubset({"secretRef", "configMapRef"}):
                        raise InputError("env_from", "envFrom contains an unknown selector.")
                    value = {key: selector for key, selector in value.items() if key != "prefix" and selector is not None}
                    if len(value) != 1:
                        raise InputError("env_from", "envFrom must contain exactly one Secret or ConfigMap selector.")
                    if "secretRef" in value:
                        secret_ref(consumer, value["secretRef"], ep + ".secretRef", False)
                    else:
                        unsupported(consumer, ep + ".configMapRef", "config_map_reference")
        for vi, item in enumerate(sequence([] if pod.get("volumes") is None else pod["volumes"], prefix + ".volumes")):
            vp = f"{prefix}.volumes[{vi}]"
            volume = mapping(item, vp)
            for key in volume:
                if key not in {"name", "emptyDir", "downwardAPI"}:
                    unsupported(consumer, vp + "." + key, "volume_source")
        for family in ("imagePullSecrets", "ephemeralContainers", "resourceClaims"):
            if family in pod:
                entries = sequence([] if pod[family] is None else pod[family], prefix + "." + family)
                if entries:
                    unsupported(consumer, prefix + "." + family, "pod_reference_family")
    counts = Counter(f["verdict"] for f in findings)
    violations = counts["phase_mismatch"]
    unknown, unsupported_count = counts["external_or_unknown"], counts["unsupported"]
    incomplete = bool(unknown or unsupported_count)
    code = 2 if incomplete else 1 if violations else 0
    status = "incomplete" if incomplete else "violations" if violations else "checked" if findings else "not_applicable"
    report["summary"] = {"status": status, "exit_code": code, "violations": violations,
                         "unknown": unknown, "unsupported": unsupported_count,
                         "incomplete": incomplete, "analysis_performed": True,
                         "verdict_counts": dict(sorted(counts.items()))}
    report["coverage"] = {
        "resources": len(resources), "consumers": consumers, "references": len(findings),
        "out_of_scope_resources": len(report["out_of_scope"]),
        "supported_reference_families": ["serviceAccountName (including implicit default)",
                                         "env.valueFrom.secretKeyRef", "envFrom.secretRef"],
        "supported_containers": ["containers", "initContainers"],
        "limits": ["Only batch/v1 Job and v1 Pod pre-install consumers.",
                   "Unsupported detected reference families make the report incomplete.",
                   "Other Kubernetes fields, hook kinds, and lifecycle events are not validated.",
                   "Not a Kubernetes schema validator; not a full chart or deployment verdict."],
    }
    return report
