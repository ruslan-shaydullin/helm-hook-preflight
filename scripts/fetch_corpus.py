#!/usr/bin/env python3
"""Fetch digest-pinned historical charts; optionally render directly into the checker.

No Kubernetes access. Raw renders, including generated Secret values, are never
written or printed. Source charts are downloaded into the ignored .corpus folder.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def fetch(url: str, digest: str, destination: Path) -> bytes:
    if destination.exists():
        data = destination.read_bytes()
    else:
        request = Request(url, headers={"User-Agent": "helm-hook-preflight-corpus"})
        with urlopen(request, timeout=60) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"checksum mismatch: {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def extract_chart(data: bytes, destination: Path) -> None:
    # Avoid links, devices and traversal on Python 3.10 too. No extractall.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("unsafe corpus archive path")
            if path.parts[0] != "datahub" or not (member.isdir() or member.isfile()):
                raise ValueError("unexpected corpus archive member")
        for member in members:
            target = destination / member.name
            # Existing paths are controlled by this local fetch destination.
            if target.is_symlink() or any(p.is_symlink() for p in target.parents):
                raise ValueError("symlink in corpus extraction destination")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("missing corpus archive member")
                with source:
                    target.write_bytes(source.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".corpus")
    parser.add_argument("--check", action="store_true", help="render in memory and save JSON reports")
    parser.add_argument("--helm", default="helm")
    parser.add_argument("--checker", default="helm-hook-preflight")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "tests/corpus.json").read_text())
    output = args.output.resolve()
    if args.check:
        for binary in (args.helm, args.checker):
            if not shutil.which(binary):
                parser.error(f"required command unavailable: {binary}")
        version = subprocess.run([args.helm, "version", "--short"], capture_output=True, check=True, text=True).stdout.strip()
        if not version.startswith("v" + manifest["helm_semantics_version"] + "+") and version != "v" + manifest["helm_semantics_version"]:
            parser.error("this corpus is validated with Helm " + manifest["helm_semantics_version"])
    receipts = []
    for fixture in manifest["fixtures"]:
        destination = output / fixture["id"]
        if "archive" in fixture:
            entry = fixture["archive"]
            data = fetch(entry["url"], entry["sha256"], output / (fixture["id"] + ".tgz"))
            extract_chart(data, destination)
        else:
            def download(entry: dict) -> None:
                fetch(entry["url"], entry["sha256"], destination / entry["path"])
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(download, fixture["files"]))
        license_source = fixture["license_source"]
        fetch(license_source["url"], license_source["sha256"], destination / "UPSTREAM-LICENSE")
        receipt = {"fixture": fixture["id"], "input_checksums_verified": True}
        if args.check:
            render_command = [args.helm, "template", manifest["release"], str(destination / fixture["chart_path"]), "--namespace", manifest["namespace"], *fixture["render_args"]]
            render = subprocess.run(render_command, capture_output=True)
            if render.returncode:
                # A template error may echo sensitive values: do not print it.
                raise ValueError(f"Helm render failed for {fixture['id']} (exit {render.returncode})")
            check_command = [args.checker, "check", "-", "--namespace", manifest["namespace"], "--mode", "install", "--format", "json"]
            result = subprocess.run(check_command, input=render.stdout, capture_output=True)
            if result.returncode not in (0, 1, 2):
                raise ValueError(f"checker failed for {fixture['id']} (exit {result.returncode})")
            report = json.loads(result.stdout)
            reports = output / "reports"
            reports.mkdir(exist_ok=True)
            (reports / (fixture["id"] + ".json")).write_text(json.dumps(report, indent=2) + "\n")
            receipt.update(render_command=render_command, checker_command=check_command, checker_exit=result.returncode,
                           render_sha256=hashlib.sha256(render.stdout).hexdigest(), report="reports/" + fixture["id"] + ".json")
        receipts.append(receipt)
        print(f"{fixture['id']}: input digests verified" + (f"; checker exit {receipt['checker_exit']}" if args.check else ""))
    output.mkdir(parents=True, exist_ok=True)
    (output / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"corpus fetch failed: {exc}") from None
