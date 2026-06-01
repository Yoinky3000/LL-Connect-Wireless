import argparse
import sys
from pathlib import Path
from typing import List
from vars import APP_NAME

# argparse derives the program name shown in usage strings from sys.argv[0].
# Set it before building the parser so the docs read 'll-connect-wireless ...'
# instead of 'gen_cli_doc.py ...'.
sys.argv[0] = APP_NAME

from cli import generate_parser
import re

ROOT_DIR = Path(__file__).resolve().parent.parent
CLI_MD = ROOT_DIR / "CLI.md"

ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def has_subparsers(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return True
    return False


def collect_group_parsers(parser: argparse.ArgumentParser, command_path: List[str]):
    output = []

    if has_subparsers(parser):
        title = " ".join(command_path)
        help_text = strip_ansi(parser.format_help())

        output.append(f"## `{title}`\n")
        output.append("```bash")
        output.append(help_text.strip())
        output.append("```\n")

        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    output.extend(
                        collect_group_parsers(subparser, command_path + [name])
                    )

    return output


def generate_cli_docs():
    parser = generate_parser()
    output = ["# CLI Documentation\n"]
    output.extend(collect_group_parsers(parser, [APP_NAME]))
    return "\n".join(output)


if __name__ == "__main__":
    CLI_MD.write_text(generate_cli_docs())
    print("CLI.md updated.")
