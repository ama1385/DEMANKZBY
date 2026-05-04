import argparse
import json
from pathlib import Path
from typing import NoReturn

from arcraiders import Client
from arcraiders.auth import BrowserOAuth
from arcraiders.auth import LocalSteamAuth
from arcraiders.auth.base import Auth
from arcraiders.auth.oauth import OAuthProvider


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    auth_group = parser.add_mutually_exclusive_group(required=True)
    auth_group.add_argument("--local-auth", choices=("steam",), dest="local_auth")
    auth_group.add_argument(
        "--web-auth",
        choices=tuple(provider.value for provider in OAuthProvider),
        dest="web_auth",
    )


def add_auth_parser(subparsers: argparse._SubParsersAction) -> None:
    token_parser = subparsers.add_parser("token")
    add_auth_args(token_parser)


def add_dump_game_data_parser(subparsers: argparse._SubParsersAction) -> None:
    dump_parser = subparsers.add_parser("dump-game-data")
    add_auth_args(dump_parser)
    dump_parser.add_argument(
        "--output",
        default="game_data.json",
        help="Path to write the game-data JSON file.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arcraiders")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_auth_parser(subparsers)
    add_dump_game_data_parser(subparsers)
    return parser


def build_auth(args: argparse.Namespace) -> Auth:
    match (args.local_auth, args.web_auth):
        case ("steam", None):
            return LocalSteamAuth()
        case (None, web_provider):
            return BrowserOAuth(OAuthProvider(web_provider))
        case _:
            raise ValueError("Specify exactly one auth mode")


def run_auth_command(args: argparse.Namespace) -> int:
    print(build_auth(args).token())
    return 0


def run_dump_game_data_command(args: argparse.Namespace) -> int:
    client = Client(build_auth(args))
    output_path = Path(args.output)
    output_path.write_text(json.dumps(client.game_data(), indent=2), encoding="utf-8")
    print(output_path.resolve())
    return 0


def exit_unknown_command(parser: argparse.ArgumentParser, command: str) -> NoReturn:
    parser.error(f"Unknown command: {command}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    match args.command:
        case "token":
            return run_auth_command(args)
        case "dump-game-data":
            return run_dump_game_data_command(args)
        case _:
            exit_unknown_command(parser, args.command)
