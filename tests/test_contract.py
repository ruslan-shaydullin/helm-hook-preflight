"""Behavioral controls for creation order, coverage, input failures, and CLI."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from helm_hook_preflight.checker import analyze
from helm_hook_preflight.model import InputError
from helm_hook_preflight.parser import parse_bundle, parse_inventory


def job(*, weight=-4, name="migration", namespace=None, pod=False):
    spec = {"serviceAccountName": "runner", "restartPolicy": "Never", "containers": [{"name": "migration", "image": "example.invalid/no-image", "env": []}]}
    meta = {"name": name, "annotations": {"helm.sh/hook": "pre-install", "helm.sh/hook-weight": str(weight)}}
    if namespace is not None:
        meta["namespace"] = namespace
    return {"apiVersion": "v1" if pod else "batch/v1", "kind": "Pod" if pod else "Job", "metadata": meta,
            "spec": spec if pod else {"template": {"spec": spec}}}


def provider(kind="ServiceAccount", name="runner", *, weight=None, namespace=None, events="pre-install"):
    meta = {"name": name}
    if weight is not None:
        meta["annotations"] = {"helm.sh/hook": events, "helm.sh/hook-weight": str(weight)}
    if namespace is not None:
        meta["namespace"] = namespace
    return {"apiVersion": "v1", "kind": kind, "metadata": meta}


def podspec(obj):
    return obj["spec"] if obj["kind"] == "Pod" else obj["spec"]["template"]["spec"]


def env_secret(obj, name="auth", optional=None, family="containers", env_from=False):
    spec = podspec(obj)
    if family not in spec:
        spec[family] = [{"name": "init", "image": "example.invalid/no-image"}]
    selector = {"name": name}
    if not env_from:
        selector["key"] = "token"
    if optional is not None:
        selector["optional"] = optional
    field = "envFrom" if env_from else "env"
    value = {"secretRef": selector} if env_from else {"name": "TOKEN", "valueFrom": {"secretKeyRef": selector}}
    spec[family][0].setdefault(field, []).append(value)


def report(*objects, inventory=None):
    return analyze(parse_bundle(yaml.safe_dump_all(objects), "fixture.yaml", "demo"), "demo", inventory)


class Ordering(unittest.TestCase):
    def test_inert_weight_and_valid_leading_zero_weight(self):
        obj = provider()
        obj["metadata"]["annotations"] = {"helm.sh/hook-weight": "abc"}
        self.assertEqual(report(obj)["summary"]["status"], "not_applicable")
        obj = provider(weight=-5)
        obj["metadata"]["annotations"]["helm.sh/hook-weight"] = "-" + "0" * 100 + "5"
        self.assertEqual(report(job(), obj)["summary"]["exit_code"], 0)

    def test_file_key_reference_is_incomplete_not_input_error(self):
        obj = job()
        podspec(obj)["containers"][0]["env"] = [{"name": "FILE", "valueFrom": {"fileKeyRef": {"volumeName": "v", "path": "p", "key": "k"}}}]
        result = report(obj, provider())
        self.assertEqual(result["summary"]["exit_code"], 2)
        self.assertEqual(result["summary"]["violations"], 1)
        self.assertEqual(result["summary"]["unsupported"], 1)
        self.assertEqual(result["findings"][1]["reason"], "file_key_reference")

    def test_inventory_empty_namespace_falls_back(self):
        for namespace in ["", None, "demo"]:
            obj = provider()
            obj["metadata"]["namespace"] = namespace
            inventory = parse_inventory(yaml.safe_dump(obj), "inventory.yaml", "demo")
            self.assertEqual(report(job(), inventory=inventory)["findings"][0]["verdict"], "declared_external")

    def test_nullable_kubernetes_fields_and_empty_env_value(self):
        for literal in ["", None]:
            obj = job()
            env_secret(obj)
            env = podspec(obj)["containers"][0]["env"][0]
            env["value"] = literal
            env["valueFrom"]["configMapKeyRef"] = None
            result = report(obj, provider(weight=-5), provider("Secret", "auth", weight=-5))
            self.assertEqual(result["findings"][1]["verdict"], "ordered_before")
        obj = job()
        podspec(obj)["serviceAccountName"] = None
        podspec(obj)["containers"][0]["env"] = [{"name": "LITERAL", "value": "x", "valueFrom": None}]
        ordinary = provider("Secret", "unused")
        ordinary["metadata"]["annotations"] = None
        self.assertEqual(report(obj, ordinary)["summary"]["exit_code"], 0)
        env_secret(obj, env_from=True)
        podspec(obj)["containers"][0]["envFrom"][0]["configMapRef"] = None
        self.assertEqual(report(obj, provider("Secret", "auth", weight=-5))["findings"][1]["verdict"], "ordered_before")

    def test_optional_null_collections_are_absent(self):
        obj = job()
        spec = podspec(obj)
        for key in ["volumes", "initContainers", "imagePullSecrets", "ephemeralContainers", "resourceClaims"]:
            spec[key] = None
        spec["containers"][0]["env"] = None
        spec["containers"][0]["envFrom"] = None
        self.assertEqual(report(obj, provider(weight=-5))["summary"]["exit_code"], 0)

    def test_earlier_main_later_equal(self):
        for weight, state, code in [(-5, "ordered_before", 0), (None, "phase_mismatch", 1), (-3, "phase_mismatch", 1), (-4, "external_or_unknown", 2)]:
            with self.subTest(weight=weight):
                result = report(job(), provider(weight=weight))
                self.assertEqual(result["findings"][0]["verdict"], state)
                self.assertEqual(result["summary"]["exit_code"], code)

    def test_namespace_and_api_group_are_identity(self):
        for dep in [provider(weight=-5, namespace="other"), {**provider(weight=-5), "apiVersion": "custom.example/v1"}]:
            result = report(job(), dep)
            self.assertEqual(result["findings"][0]["reason"], "provider_not_in_bundle")
        result = report(job(namespace="other"), provider(weight=-5, namespace="other"))
        self.assertEqual(result["summary"]["exit_code"], 0)
        self.assertEqual(result["findings"][0]["dependency"]["namespace"], "other")

    def test_cluster_namespace_not_invented(self):
        result = report({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "demo"}})
        self.assertIsNone(result["out_of_scope"][0]["resource"]["identity"]["namespace"])

    def test_default_service_account_is_assumption(self):
        for explicit in [None, "", "default"]:
            obj = job()
            if explicit is None:
                del podspec(obj)["serviceAccountName"]
            else:
                podspec(obj)["serviceAccountName"] = explicit
            finding = report(obj)["findings"][0]
            self.assertEqual(finding["verdict"], "assumed_available")
            self.assertIn("RBAC", finding["explanation"])

    def test_inventory_is_assertion_even_for_main_provider(self):
        inventory = parse_inventory(yaml.safe_dump(provider()), "inventory.yaml", "demo")
        result = report(job(), provider(), inventory=inventory)
        self.assertEqual(result["findings"][0]["verdict"], "declared_external")
        self.assertIn("not live verified", result["findings"][0]["explanation"])

    def test_mixed_violation_and_unknown_preserved(self):
        obj = job()
        env_secret(obj, "external")
        result = report(obj, provider())
        self.assertEqual((result["summary"]["violations"], result["summary"]["unknown"], result["summary"]["exit_code"]), (1, 1, 2))

    def test_multiple_events_and_success_cleanup(self):
        dep = provider(weight=-5, events="pre-install,pre-upgrade")
        dep["metadata"]["annotations"]["helm.sh/hook-delete-policy"] = "before-hook-creation,hook-succeeded"
        self.assertEqual(report(job(), dep)["summary"]["exit_code"], 0)
        dep["metadata"]["annotations"]["helm.sh/hook"] = "post-install,pre-upgrade"
        self.assertEqual(report(job(), dep)["findings"][0]["reason"], "provider_not_pre_install")

    def test_earlier_provider_does_not_check_image_or_rbac(self):
        result = report(job(), provider(weight=-5))
        self.assertEqual(result["summary"]["exit_code"], 0)
        self.assertTrue(any("RBAC" in a and "images" in a for a in result["assumptions"]))

    def test_secrets_all_supported_positions_and_optional(self):
        for pod in [False, True]:
            for family in ["containers", "initContainers"]:
                for env_from in [False, True]:
                    for optional in [False, True]:
                        with self.subTest(pod=pod, family=family, env_from=env_from, optional=optional):
                            obj = job(pod=pod)
                            env_secret(obj, optional=optional, family=family, env_from=env_from)
                            result = report(obj, provider(weight=-5))
                            secret = result["findings"][1]
                            self.assertEqual(secret["verdict"], "not_required" if optional else "external_or_unknown")
                            self.assertIn(family + "[0]", secret["reference_path"])

    def test_secret_provider_main_to_hook(self):
        obj = job()
        env_secret(obj)
        before = report(obj, provider(weight=-5), provider("Secret", "auth"))
        after = report(obj, provider(weight=-5), provider("Secret", "auth", weight=-5))
        self.assertEqual(before["findings"][1]["verdict"], "phase_mismatch")
        self.assertEqual(after["findings"][1]["verdict"], "ordered_before")

    def test_no_hooks_is_not_applicable(self):
        result = report(provider())
        self.assertEqual(result["summary"]["status"], "not_applicable")
        self.assertEqual(result["coverage"]["references"], 0)

    def test_other_events_and_hook_kinds_reported(self):
        obj = job()
        obj["metadata"]["annotations"]["helm.sh/hook"] = "pre-upgrade"
        result = report(obj, provider(weight=-5))
        self.assertEqual(result["coverage"]["out_of_scope_resources"], 2)
        self.assertEqual(result["summary"]["status"], "not_applicable")

    def test_unsupported_references_incomplete(self):
        obj = job()
        spec = podspec(obj)
        spec["containers"][0]["env"] = [{"name": "SETTING", "valueFrom": {"configMapKeyRef": {"name": "settings", "key": "key"}}}]
        spec["volumes"] = [{"name": "data", "projected": {"sources": [{"secret": {"name": "mount"}}]}}]
        spec["imagePullSecrets"] = [{"name": "pull"}]
        result = report(obj, provider(weight=-5))
        self.assertEqual(result["summary"]["unsupported"], 3)
        self.assertEqual(result["summary"]["exit_code"], 2)

    def test_source_comment_and_document_number(self):
        raw = "---\n# Source: chart/templates/job.yaml\n" + yaml.safe_dump(job())
        finding = analyze(parse_bundle(raw, "with spaces.yaml", "demo"), "demo")["findings"][0]
        self.assertEqual(finding["consumer"]["source"]["template"], "chart/templates/job.yaml")
        self.assertEqual(finding["consumer"]["source"]["document"], 1)

    def test_secret_values_absent_from_report(self):
        secret = provider("Secret", "auth", weight=-5)
        secret["data"] = {"token": "CANARY_SECRET_DO_NOT_REPORT"}
        secret["stringData"] = {"private": "ANOTHER_CANARY"}
        obj = job()
        env_secret(obj)
        serialized = json.dumps(report(obj, secret))
        self.assertNotIn("CANARY", serialized)
        self.assertNotIn("stringData", serialized)


class InvalidInput(unittest.TestCase):
    def test_malformed_empty_alias_list_duplicate_timestamp(self):
        cases = ["", "# comment", "kind: [", "a: &a [*a]", "null", "[]", "a: 1\na: 2", "apiVersion: v1\nkind: List\nitems: []", "date: 2026-99-99", "!!python/object:foo {}"]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(InputError):
                parse_bundle(raw, "fixture.yaml", "demo")

    def test_duplicate_identity_and_namespace_controls(self):
        with self.assertRaisesRegex(InputError, "Duplicate resource identity"):
            report(job(), provider(), provider(weight=-5))
        self.assertEqual(report(job(), provider(weight=-5), provider(namespace="other"))["summary"]["exit_code"], 0)

    def test_optional_must_be_boolean(self):
        for value in ["false", "true", 0, 1, {}, []]:
            obj = job()
            env_secret(obj, optional=value)
            with self.subTest(value=value), self.assertRaises(InputError):
                report(obj)

    def test_bad_hook_metadata_and_shapes(self):
        for field, value in [("helm.sh/hook", "pre-install,bogus"), ("helm.sh/hook", ""), ("helm.sh/hook-weight", 1), ("helm.sh/hook-weight", "NaN"), ("helm.sh/hook-weight", str(2**64)), ("helm.sh/hook-delete-policy", "instantly")]:
            obj = job()
            obj["metadata"]["annotations"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(InputError):
                report(obj)
        for value in [None, {}, [], ""]:
            obj = job()
            podspec(obj)["containers"] = value
            with self.assertRaises(InputError):
                report(obj)

    def test_inventory_rejects_values(self):
        obj = provider("Secret", "auth")
        obj["data"] = {"token": "CANARY"}
        with self.assertRaises(InputError):
            parse_inventory(yaml.safe_dump(obj), "inventory.yaml", "demo")


class CLI(unittest.TestCase):
    def invoke(self, raw, args=(), file=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file with spaces.yaml"
            path.write_text(raw)
            command = [sys.executable, "-m", "helm_hook_preflight.cli", "check", str(path) if file else "-", "--namespace", "demo", "--mode", "install", *args]
            return subprocess.run(command, input=raw, text=True, capture_output=True)

    def test_file_stdin_json_text_exit_codes(self):
        for objects, expected in [([job(), provider(weight=-5)], 0), ([job(), provider()], 1), ([job()], 2), ([], 3)]:
            raw = yaml.safe_dump_all(objects)
            for file in [False, True]:
                for fmt in ["text", "json"]:
                    with self.subTest(code=expected, file=file, fmt=fmt):
                        result = self.invoke(raw, ["--format", fmt], file)
                        self.assertEqual(result.returncode, expected, result.stderr)
                        self.assertNotIn("Traceback", result.stderr)
                        if fmt == "json":
                            self.assertEqual(json.loads(result.stdout)["summary"]["exit_code"], expected)

    def test_bad_arguments_json_and_invalid_mode(self):
        result = self.invoke(yaml.safe_dump(job()), ["--mode", "upgrade", "--format=json"])
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["errors"][0]["code"], "arguments")

    def test_invalid_timestamp_redacted_json_error(self):
        result = self.invoke("date: 2026-99-99\nprivate: CANARY", ["--format", "json"])
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("CANARY", result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
