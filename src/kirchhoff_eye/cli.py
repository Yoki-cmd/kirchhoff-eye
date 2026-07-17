"""Top-level Kirchhoff-eye command line interface."""

import argparse
from typing import Optional, Sequence

from . import __version__
from .doctor import run as run_doctor
from .label_positions import apply_file
from .pipeline import approve, build, repair, review


def _add_build_options(parser: argparse.ArgumentParser, *, source: bool = False) -> None:
    if source:
        parser.add_argument("source")
    parser.add_argument("ir_file")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dpi", type=int, default=300)


def _add_review_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("job_dir")
    parser.add_argument("review_file")


def _add_repair_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("job_dir")
    parser.add_argument("ir_file")
    parser.add_argument("--patches", required=True)
    parser.add_argument("--dpi", type=int, default=300)


def _add_approve_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("job_dir")
    parser.add_argument("--note", default="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kirchhoff-eye",
        description=(
            "Kirchhoff-eye: agent-facing circuit drawing workflows over a deterministic "
            "canonical JSON IR and circuitikz backend."
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

    review_cmd = commands.add_parser(
        "review",
        help="record one complete per-region source comparison review",
    )
    _add_review_options(review_cmd)
    review_cmd.set_defaults(handler=_run_review)

    repair_cmd = commands.add_parser(
        "repair",
        help="build the next reviewed IR round and record applied patch operations",
    )
    _add_repair_options(repair_cmd)
    repair_cmd.set_defaults(handler=_run_repair)

    approve_cmd = commands.add_parser(
        "approve",
        help="explicitly approve a clean reviewed job",
    )
    _add_approve_options(approve_cmd)
    approve_cmd.set_defaults(handler=_run_approve)

    task_cmd = commands.add_parser(
        "task",
        help="route agent tasks through the canonical IR backend",
    )
    task_commands = task_cmd.add_subparsers(dest="task_command", required=True)

    redraw_cmd = task_commands.add_parser(
        "redraw-image",
        help="render an agent-reviewed IR for a source image and open a review round",
    )
    _add_build_options(redraw_cmd, source=True)
    redraw_cmd.set_defaults(handler=_run_task_redraw)

    description_cmd = task_commands.add_parser(
        "draw-from-description",
        help="record a natural-language brief and render its agent-authored canonical IR",
    )
    description_cmd.add_argument("description_file")
    description_cmd.add_argument("ir_file")
    description_cmd.add_argument("--out", required=True)
    description_cmd.add_argument("--dpi", type=int, default=300)
    description_cmd.set_defaults(handler=_run_task_description)

    netlist_cmd = task_commands.add_parser(
        "draw-from-netlist",
        help="record a netlist and render its agent-authored canonical IR",
    )
    netlist_cmd.add_argument("netlist_file")
    netlist_cmd.add_argument("ir_file")
    netlist_cmd.add_argument("--out", required=True)
    netlist_cmd.add_argument("--dpi", type=int, default=300)
    netlist_cmd.set_defaults(handler=_run_task_netlist)

    edit_cmd = task_commands.add_parser(
        "edit-ir",
        help="record an edit request and render the resulting agent-edited canonical IR",
    )
    edit_cmd.add_argument("request_file")
    edit_cmd.add_argument("ir_file")
    edit_cmd.add_argument("--out", required=True)
    edit_cmd.add_argument("--dpi", type=int, default=300)
    edit_cmd.set_defaults(handler=_run_task_edit)

    task_review_cmd = task_commands.add_parser("review", help="record a round review")
    _add_review_options(task_review_cmd)
    task_review_cmd.set_defaults(handler=_run_review)

    task_repair_cmd = task_commands.add_parser("repair", help="generate the next repair round")
    _add_repair_options(task_repair_cmd)
    task_repair_cmd.set_defaults(handler=_run_repair)

    render_cmd = task_commands.add_parser(
        "render",
        help="validate and render an existing canonical IR without source comparison",
    )
    _add_build_options(render_cmd)
    render_cmd.set_defaults(handler=_run_task_render)

    task_approve_cmd = task_commands.add_parser("approve", help="approve a clean reviewed job")
    _add_approve_options(task_approve_cmd)
    task_approve_cmd.set_defaults(handler=_run_approve)

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


def _run_review(args: argparse.Namespace) -> int:
    return review(args.job_dir, args.review_file)


def _run_repair(args: argparse.Namespace) -> int:
    return repair(args.job_dir, args.ir_file, args.patches, dpi=args.dpi)


def _run_approve(args: argparse.Namespace) -> int:
    return approve(args.job_dir, note=args.note)


def _run_task_redraw(args: argparse.Namespace) -> int:
    return build(
        args.ir_file,
        args.out,
        source=args.source,
        dpi=args.dpi,
        task_kind="redraw-image",
    )


def _run_task_description(args: argparse.Namespace) -> int:
    return build(
        args.ir_file,
        args.out,
        dpi=args.dpi,
        task_kind="draw-from-description",
        task_input=(args.description_file, "description.txt"),
    )


def _run_task_netlist(args: argparse.Namespace) -> int:
    return build(
        args.ir_file,
        args.out,
        dpi=args.dpi,
        task_kind="draw-from-netlist",
        task_input=(args.netlist_file, "netlist.txt"),
    )


def _run_task_edit(args: argparse.Namespace) -> int:
    return build(
        args.ir_file,
        args.out,
        dpi=args.dpi,
        task_kind="edit-ir",
        task_input=(args.request_file, "edit-request.txt"),
    )


def _run_task_render(args: argparse.Namespace) -> int:
    return build(args.ir_file, args.out, dpi=args.dpi, task_kind="render")


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
