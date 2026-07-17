"""Top-level Kirchhoff-eye command line interface."""

import argparse
from typing import Optional, Sequence

from . import __version__
from .doctor import run as run_doctor
from .label_positions import apply_file
from .pipeline import build


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kirchhoff-eye",
        description=(
            "Kirchhoff-eye: AI-assisted circuit redrawing with a deterministic "
            "JSON IR and circuitikz backend."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    commands = parser.add_subparsers(dest="command")
    build_cmd = commands.add_parser(
        "build",
        help="validate, serialize, render, inspect, and report a canonical IR",
    )
    build_cmd.add_argument("ir_file")
    build_cmd.add_argument("--source")
    build_cmd.add_argument("--out", required=True)
    build_cmd.add_argument("--dpi", type=int, default=300)
    build_cmd.set_defaults(handler=_run_build)

    labels_cmd = commands.add_parser(
        "labels",
        help="apply reproducible human-approved component label coordinates",
    )
    label_commands = labels_cmd.add_subparsers(dest="labels_command", required=True)
    apply_cmd = label_commands.add_parser(
        "apply",
        help="apply a component-ID to [x, y] positions file to a canonical IR",
    )
    apply_cmd.add_argument("ir_file")
    apply_cmd.add_argument("positions_file")
    apply_cmd.add_argument("-o", "--output", required=True)
    apply_cmd.set_defaults(handler=_run_labels_apply)

    doctor_cmd = commands.add_parser(
        "doctor",
        help="check the Python, resource, TeX, and rasterization environment",
        description="Check the environment required by the deterministic build pipeline.",
    )
    doctor_cmd.add_argument(
        "--json",
        action="store_true",
        help="print a machine-readable diagnostic report",
    )
    doctor_cmd.set_defaults(handler=_run_doctor)
    return parser


def _run_build(args: argparse.Namespace) -> int:
    return build(args.ir_file, args.out, source=args.source, dpi=args.dpi)


def _run_labels_apply(args: argparse.Namespace) -> int:
    return apply_file(args.ir_file, args.positions_file, args.output)


def _run_doctor(args: argparse.Namespace) -> int:
    return run_doctor(json_output=args.json)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args_list = list(argv) if argv is not None else None
    if args_list == []:
        parser.print_help()
        return 0
    args = parser.parse_args(args_list)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
