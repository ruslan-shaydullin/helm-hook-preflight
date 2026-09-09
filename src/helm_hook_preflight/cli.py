"""CLI I/O and reporting, separate from the order analyzer."""
import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checker import analyze, error_report
from .model import InputError
from .parser import MAX_BYTES, parse_bundle, parse_inventory


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argparse includes arbitrary argument values. Keep errors payload-free.
        raise InputError("arguments", "Invalid arguments; see helm-hook-preflight check --help.")


def parser():
    result = Parser(description="Check bounded Helm hook creation order offline (Helm 4.2.4 semantics).")
    result.add_argument("--version", action="version", version=__version__)
    sub = result.add_subparsers(dest="command", required=True, parser_class=Parser)
    check = sub.add_parser("check", help="Analyze a complete rendered YAML bundle.")
    check.add_argument("file", help="Rendered YAML file, or - for stdin.")
    check.add_argument("--namespace", required=True, help="Effective release namespace; required even for explicit resource namespaces.")
    check.add_argument("--mode", required=True, choices=["install"], help="Explicit fresh first-install model only.")
    check.add_argument("--format", choices=["text", "json"], default="text")
    check.add_argument("--external-inventory", help="Identity-only YAML asserting preexisting Secret/ServiceAccount resources.")
    return result


def read_input(path: str) -> str:
    try:
        if path == "-":
            data = sys.stdin.buffer.read(MAX_BYTES + 1)
        else:
            with Path(path).open("rb") as stream:
                data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise InputError("input_limit", "Input exceeds the 16 MiB limit.")
        return data.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("input_read", "Cannot read a UTF-8 input file/stream; check path and permissions.") from None


def clean(value):
    return str(value).encode("unicode_escape").decode("ascii")


def render_text(report):
    summary = report["summary"]
    lines = [f"helm-hook-preflight: {summary['status']} (exit {summary['exit_code']})",
             f"Model: fresh first install; Helm semantics {report['helm_semantics_version']}; namespace {clean(report['namespace'])}",
             f"Violations: {summary['violations']}; unknown: {summary['unknown']}; unsupported: {summary['unsupported']}"]
    for error in report["errors"]:
        lines.append(f"ERROR [{error['code']}] {clean(error['message'])}")
    for finding in report["findings"]:
        consumer = finding["consumer"]["identity"]
        dependency = finding["dependency"]
        target = f"{dependency['kind']}/{dependency['namespace']}/{dependency['name']}" if dependency else "unsupported reference"
        source = finding["consumer"]["source"]
        lines.extend([f"{finding['verdict']} [{finding['reason']}]: {clean(consumer['kind'])}/{clean(consumer['namespace'])}/{clean(consumer['name'])} -> {clean(target)}",
                      f"  {clean(source['file'])}:document {source['document']} {clean(finding['reference_path'])}",
                      f"  {finding['explanation']}"])
    coverage = report["coverage"]
    if coverage.get("resources") is not None:
        lines.append(f"Coverage: {coverage['consumers']} pre-install Job/Pod consumers; {coverage['references']} reference results; {coverage['out_of_scope_resources']} other resources outside consumer scope.")
    lines.append("Assumptions:")
    lines.extend("- " + a for a in report["assumptions"])
    lines.append("This is a bounded creation-order check, not an installation guarantee.")
    return "\n".join(lines)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    # Preserve machine-readable input errors even when argument parsing fails.
    json_output = "--format=json" in args or any(a == "--format" and i + 1 < len(args) and args[i + 1] == "json" for i, a in enumerate(args))
    namespace = None
    try:
        parsed = parser().parse_args(args)
        namespace, json_output = parsed.namespace, parsed.format == "json"
        if parsed.file == "-" and parsed.external_inventory == "-":
            raise InputError("stdin_conflict", "Bundle and inventory cannot both read stdin.")
        resources = parse_bundle(read_input(parsed.file), parsed.file, namespace)
        inventory = parse_inventory(read_input(parsed.external_inventory), parsed.external_inventory, namespace) if parsed.external_inventory else set()
        report = analyze(resources, namespace, inventory)
    except InputError as exc:
        report = error_report(exc, namespace)
        print(f"helm-hook-preflight: {exc.code}: {exc}", file=sys.stderr)
    output = json.dumps(report, indent=2, ensure_ascii=True) if json_output else render_text(report)
    print(output)
    return report["summary"]["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
