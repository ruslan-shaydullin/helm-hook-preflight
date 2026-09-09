"""Opt-in real upstream regression corpus; fetch sources before running.

HHP_CORPUS=/path/to/fetched-corpus python -m unittest discover -s tests -v
No chart install and no render persistence. Default unit tests stay offline.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from helm_hook_preflight.checker import analyze
from helm_hook_preflight.parser import parse_bundle


@unittest.skipUnless(os.environ.get("HHP_CORPUS"), "set HHP_CORPUS to digest-verified source directory")
class HistoricalCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(os.environ["HHP_CORPUS"])
        cls.manifest = json.loads((Path(__file__).parent / "corpus.json").read_text())
        if not shutil.which("helm"):
            raise unittest.SkipTest("Helm 4.2.4 is required for real corpus rendering")
        version = subprocess.run(["helm", "version", "--short"], capture_output=True, text=True, check=True).stdout.strip()
        if version.split("+", 1)[0] != "v4.2.4":
            raise unittest.SkipTest("the real corpus is pinned to Helm 4.2.4")

    def report(self, name):
        fixture = next(f for f in self.manifest["fixtures"] if f["id"] == name)
        chart = self.directory / name / fixture["chart_path"]
        self.assertTrue(chart.is_dir(), "fetch sources with scripts/fetch_corpus.py first")
        result = subprocess.run(["helm", "template", "screen", str(chart), "--namespace", "probe", *fixture["render_args"]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "historical chart render failed; output suppressed")
        return analyze(parse_bundle(result.stdout, name + ".yaml", "probe"), "probe")

    def test_greenkube_same_reference_family_changes_order(self):
        for version, expected, exit_code in (("v0.2.4", "phase_mismatch", 1), ("v0.2.5", "ordered_before", 0)):
            with self.subTest(version=version):
                report = self.report("greenkube-" + version)
                self.assertEqual(report["summary"]["exit_code"], exit_code)
                self.assertEqual(len(report["findings"]), 1)
                finding = report["findings"][0]
                self.assertEqual(finding["verdict"], expected)
                self.assertEqual(finding["dependency"]["namespace"], "probe")
                self.assertEqual(finding["reference_path"], "spec.template.spec.serviceAccountName")
                self.assertEqual(finding["consumer"]["source"]["template"], "greenkube/templates/pre-install-check.yaml")

    def test_datahub_auth_fixed_but_mysql_remains_unknown(self):
        for version, expected, violations in (("0.8.20", "phase_mismatch", 3), ("0.8.21", "ordered_before", 0)):
            with self.subTest(version=version):
                report = self.report("datahub-" + version)
                self.assertEqual(report["summary"]["exit_code"], 2)
                self.assertEqual(report["summary"]["violations"], violations)
                auth = [f for f in report["findings"] if f["dependency"] and f["dependency"]["name"] == "datahub-auth-secrets"]
                mysql = [f for f in report["findings"] if f["dependency"] and f["dependency"]["name"] == "mysql-secrets"]
                self.assertEqual(len(auth), 3)
                self.assertEqual({f["verdict"] for f in auth}, {expected})
                self.assertEqual(len(mysql), 1)
                self.assertEqual(mysql[0]["verdict"], "external_or_unknown")
                self.assertEqual(mysql[0]["dependency"]["namespace"], "probe")
                self.assertTrue(all(f["reference_path"].endswith(".valueFrom.secretKeyRef") for f in auth + mysql))


if __name__ == "__main__":
    unittest.main()
