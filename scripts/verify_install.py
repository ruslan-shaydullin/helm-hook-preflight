#!/usr/bin/env python3
"""Build-path-independent wheel/sdist installation and CLI acceptance checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", help="Local wheel/sdist path, or public release URL.")
    parser.add_argument("--tests", action="store_true", help="Also run offline contract tests against the installed build.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifact = args.artifact if args.artifact.startswith("https://") else str(Path(args.artifact).resolve())
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("HHP_CORPUS", None)
    with tempfile.TemporaryDirectory(prefix="hhp-install-") as tmp:
        directory = Path(tmp)
        target = directory / "venv"
        venv.EnvBuilder(with_pip=True).create(target)
        binary = target / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", artifact], cwd=directory, env=env, check=True, stdout=subprocess.DEVNULL)
        module = subprocess.check_output([str(python), "-c", "import helm_hook_preflight; print(helm_hook_preflight.__file__)"], cwd=directory, env=env, text=True).strip()
        if not Path(module).resolve().is_relative_to(target.resolve()):
            raise RuntimeError("Import did not resolve inside the newly installed build environment")
        receipts = []
        for name, expected in [("bad", 1), ("good", 0), ("unknown", 2), ("invalid", 3)]:
            path = directory / f"{name} input.yaml"
            shutil.copyfile(root / "examples" / (name + ".yaml"), path)
            command = [str(python), "-m", "helm_hook_preflight.cli", "check", str(path), "--namespace", "demo", "--mode", "install", "--format", "json"]
            result = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True)
            report = json.loads(result.stdout)
            if result.returncode != expected or report["summary"]["exit_code"] != expected:
                raise RuntimeError(f"Installed example {name} violated exit contract")
            if "Traceback" in result.stderr:
                raise RuntimeError("Installed CLI emitted a traceback")
            receipts.append({"example": name, "expected": expected, "actual": result.returncode, "summary": report["summary"]})
        if args.tests:
            tests = directory / "tests"
            tests.mkdir()
            shutil.copyfile(root / "tests" / "test_contract.py", tests / "test_contract.py")
            subprocess.run([str(python), "-m", "unittest", "discover", "-s", str(tests), "-v"], cwd=directory, env=env, check=True)
        print(json.dumps({"artifact": artifact, "sha256": None if artifact.startswith("https://") else hashlib.sha256(Path(artifact).read_bytes()).hexdigest(),
                          "python": sys.version.split()[0], "import_path": module, "source_tree_import": False, "checks": receipts}, indent=2))


if __name__ == "__main__":
    main()
