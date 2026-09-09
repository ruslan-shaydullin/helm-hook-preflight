"""Strict, bounded YAML input. Error messages never include YAML values."""
import re
from typing import Any

import yaml

from .model import Identity, InputError, Resource

MAX_BYTES = 16 * 1024 * 1024
EVENTS = {"pre-install", "post-install", "pre-upgrade", "post-upgrade", "pre-delete",
          "post-delete", "pre-rollback", "post-rollback", "test", "test-success"}
POLICIES = {"before-hook-creation", "hook-succeeded", "hook-failed"}
NAMESPACED = {
    ("", k) for k in ("Pod", "ServiceAccount", "Secret", "ConfigMap", "Service",
                       "PersistentVolumeClaim", "ReplicationController", "Endpoints", "ResourceQuota", "LimitRange")
} | {(g, k) for g, kinds in {
    "batch": ("Job", "CronJob"), "apps": ("Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"),
    "rbac.authorization.k8s.io": ("Role", "RoleBinding"),
    "networking.k8s.io": ("Ingress", "NetworkPolicy"),
    "policy": ("PodDisruptionBudget",), "autoscaling": ("HorizontalPodAutoscaler",),
}.items() for k in kinds}
CLUSTER_SCOPED = {("", k) for k in ("Namespace", "Node", "PersistentVolume")} | {
    ("rbac.authorization.k8s.io", "ClusterRole"), ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("apiextensions.k8s.io", "CustomResourceDefinition"), ("storage.k8s.io", "StorageClass"),
    ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration"),
}


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise InputError("yaml_key", "YAML mapping keys must be strings.")
            if key in result:
                raise InputError("duplicate_key", "Duplicate YAML mapping key.")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def mapping(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise InputError("field_type", f"Expected a mapping at {path}.")
    return value


def sequence(value: Any, path: str) -> list:
    if not isinstance(value, list):
        raise InputError("field_type", f"Expected a list at {path}.")
    return value


def string(value: Any, path: str, *, empty=False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise InputError("field_type", f"Expected a {'possibly empty ' if empty else 'nonempty '}string at {path}.")
    return value


def load_documents(text: str, filename: str) -> list[tuple[dict, dict]]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise InputError("input_limit", "Input exceeds the 16 MiB limit.")
    starts, depth, count = [], 0, 0
    try:
        for event in yaml.parse(text, Loader=StrictLoader):
            count += 1
            if count > 500_000:
                raise InputError("input_limit", "Input exceeds the YAML event limit.")
            if isinstance(event, yaml.AliasEvent):
                raise InputError("yaml_alias", "YAML aliases are unsupported; expand them before checking.")
            if isinstance(event, yaml.DocumentStartEvent):
                starts.append(event.start_mark.line)
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                if depth > 80:
                    raise InputError("input_limit", "YAML nesting exceeds 80 levels.")
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
        if len(starts) > 10_000:
            raise InputError("input_limit", "Input exceeds the document limit.")
        documents = list(yaml.load_all(text, Loader=StrictLoader))
    except InputError:
        raise
    except (yaml.YAMLError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise InputError("invalid_yaml", f"Invalid or unsupported YAML{location}; values omitted.") from None
    lines, result = text.splitlines(), []
    for i, obj in enumerate(documents):
        if obj is None:
            continue  # Helm commonly emits empty template documents.
        mapping(obj, f"document[{i + 1}]")
        end = starts[i + 1] if i + 1 < len(starts) else len(lines)
        source = {"file": filename, "document": i + 1, "line": starts[i] + 1}
        for line in lines[starts[i]:end]:
            match = re.match(r"^# Source: (.+)$", line)
            if match:
                source["template"] = match.group(1)
                break
        result.append((obj, source))
    if not result:
        raise InputError("empty_input", "No resource documents found.")
    return result


def parse_bundle(text: str, filename: str, namespace: str) -> list[Resource]:
    string(namespace, "--namespace")
    resources, identities = [], set()
    for obj, source in load_documents(text, filename):
        api = string(obj.get("apiVersion"), "apiVersion")
        kind = string(obj.get("kind"), "kind")
        group = api.rsplit("/", 1)[0] if "/" in api else ""
        if kind == "List":
            raise InputError("list_unsupported", "List wrappers are unsupported: provide individual rendered Helm resource documents.")
        meta = mapping(obj.get("metadata"), "metadata")
        name = string(meta.get("name"), "metadata.name")
        ns = meta.get("namespace")
        if ns is not None:
            string(ns, "metadata.namespace", empty=True)
        if (group, kind) in NAMESPACED:
            ns = ns or namespace
        elif (group, kind) in CLUSTER_SCOPED:
            if ns:
                raise InputError("cluster_namespace", "A known cluster-scoped resource declares a namespace.")
            ns = None
        # Unknown API scope is not guessed; these objects are outside reference matching.
        identity = Identity(group, kind, name, ns or None)
        if identity in identities:
            raise InputError("duplicate_identity", "Duplicate resource identity; provider selection would be ambiguous.")
        identities.add(identity)
        annotations = mapping({} if meta.get("annotations") is None else meta["annotations"], "metadata.annotations")
        for value in annotations.values():
            string(value, "metadata.annotations value", empty=True)
        hook = annotations.get("helm.sh/hook")
        events = tuple(s.strip() for s in hook.split(",")) if hook is not None else ()
        if any(e not in EVENTS for e in events) or len(set(events)) != len(events):
            raise InputError("hook_events", "Unsupported, empty, or duplicate Helm hook event annotation.")
        raw_weight = annotations.get("helm.sh/hook-weight", "0")
        if not re.fullmatch(r"[+-]?[0-9]+", raw_weight) or len(raw_weight) > 20:
            raise InputError("hook_weight", "Hook weight must be a quoted decimal 64-bit integer.")
        weight = int(raw_weight)
        if not -(2**63) <= weight < 2**63:
            raise InputError("hook_weight", "Hook weight is outside the signed 64-bit range.")
        policies = tuple(p.strip() for p in annotations.get("helm.sh/hook-delete-policy", "before-hook-creation").split(",")) if events else ()
        if any(p not in POLICIES for p in policies):
            raise InputError("hook_delete_policy", "Unrecognized hook deletion policy.")
        resources.append(Resource(identity, api, events, weight, policies, source, obj))
    return resources


def parse_inventory(text: str, filename: str, namespace: str) -> set[Identity]:
    """Accept identity-only v1 Secret/SA YAML; never Secret payloads."""
    result = set()
    for obj, _ in load_documents(text, filename):
        if set(obj) != {"apiVersion", "kind", "metadata"}:
            raise InputError("inventory_shape", "Inventory accepts only apiVersion, kind, metadata; no Secret values.")
        if obj["apiVersion"] != "v1" or obj["kind"] not in ("Secret", "ServiceAccount"):
            raise InputError("inventory_kind", "Inventory supports v1 Secret and ServiceAccount identities only.")
        meta = mapping(obj["metadata"], "inventory.metadata")
        if not set(meta).issubset({"name", "namespace"}) or "name" not in meta:
            raise InputError("inventory_shape", "Inventory metadata accepts only name and namespace.")
        identity = Identity("", obj["kind"], string(meta["name"], "inventory.metadata.name"),
                            string(meta.get("namespace", namespace), "inventory.metadata.namespace"))
        if identity in result:
            raise InputError("duplicate_identity", "Duplicate inventory identity.")
        result.add(identity)
    return result
