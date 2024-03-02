#!/usr/bin/env python3

import argparse
import fnmatch
import os
import shlex
import stat
import subprocess
from dataclasses import dataclass
from typing import Iterator

from dircolors import Dircolors
from igittigitt import IgnoreParser


XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
DEFAULT_RC_FILE = os.path.join(XDG_CONFIG_HOME, "erd.rc")
DIRCOLORS = Dircolors()


class Entity:
    def __init__(self, path: str, preserve_path: bool = False) -> None:
        self.path = path
        self.preserve_path = preserve_path
        self.dirname, self.basename = os.path.split(path)
        self.stat = os.lstat(self.path)

    def __str__(self) -> str:
        return self.path

    def children(self) -> list["Entity"]:
        if not stat.S_ISDIR(self.stat.st_mode):
            return []

        children = [
            Entity(os.path.join(self.path, child)) for child in os.listdir(self.path)
        ]
        children.sort(key=lambda e: (stat.S_ISDIR(e.stat.st_mode), e.basename))
        return children

    def format(self) -> str:
        if self.preserve_path:
            cwd = None
            result = DIRCOLORS.format(self.path, cwd=cwd)
        else:
            cwd = self.dirname or None
            result = DIRCOLORS.format(self.basename, cwd=cwd)

        # Add special prefixes for entities that aren't regular files.
        # NOTE: No special handling for S_ISCHR, S_ISBLK, S_ISPORT, or S_ISWHT
        if stat.S_ISDIR(self.stat.st_mode):
            result += "/"
        elif stat.S_ISREG(self.stat.st_mode) and os.access(self.path, os.X_OK):
            result += "*"
        elif stat.S_ISFIFO(self.stat.st_mode):
            result += "|"
        elif stat.S_ISLNK(self.stat.st_mode):
            target = os.readlink(self.path)
            result += "@ -> " + DIRCOLORS.format(target, cwd=cwd)
        elif stat.S_ISSOCK(self.stat.st_mode):
            result += "="
        elif stat.S_ISDOOR(self.stat.st_mode):
            result += ">"

        return result


class PathMatch:
    def __init__(self, expression: str):
        self.pattern = expression.rstrip("/")
        self.is_dir = expression.endswith("/")

    def __call__(self, entity: Entity) -> bool:
        if self.is_dir and not stat.S_ISDIR(entity.stat.st_mode):
            return False
        return fnmatch.fnmatch(entity.basename, self.pattern)

    def __str__(self) -> str:
        return f"{self.pattern}{'/' if self.is_dir else ''}"


@dataclass
class PathFilter:
    include: list[PathMatch]
    exclude: list[PathMatch]
    gitignore: IgnoreParser | None

    def __call__(self, entity: Entity) -> bool:
        retain = True
        if self.include:
            retain = any(pmatch(entity) for pmatch in self.include)
        if retain and self.exclude:
            retain = not any(pmatch(entity) for pmatch in self.exclude)
        if retain and self.gitignore:
            retain = not self.gitignore.match(entity.path)
        return retain


def make_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", default=["."], nargs="*")
    parser.add_argument("--include", "-P", default="")
    parser.add_argument("--exclude", "-I", default="")
    parser.add_argument("--gitignore", action="store_true", default=False)
    return parser


def parse_rc_file(path: str) -> list[str]:
    try:
        with open(path, "r") as f:
            lexer = shlex.shlex(f)
            lexer.whitespace_split = True
            return list(lexer)
    except FileNotFoundError:
        return []


def combine_argv_and_rc(rc: str | None, argv: list[str] | None) -> list[str]:
    return (parse_rc_file(rc) if rc else []) + (argv or [])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = make_argument_parser()
    rc_group = parser.add_mutually_exclusive_group()
    rc_group.add_argument("--rc", default=DEFAULT_RC_FILE)
    rc_group.add_argument("--no-rc", dest="rc", action="store_false")
    args = parser.parse_args(argv)

    argv = combine_argv_and_rc(args.rc, argv)
    parser = make_argument_parser()
    return parser.parse_args(argv)


def make_ignore_parser() -> IgnoreParser:
    try:
        p = subprocess.run(
            ["git", "rev-parser", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        top = p.stdout.decode().strip()
    except subprocess.CalledProcessError:
        top = os.getcwd()
    parser = IgnoreParser()
    parser.parse_rule_files(base_dir=top, add_default_patterns=True)
    return parser


def tree_walk(
    entity: Entity,
    ancestors: list[Entity],
    filter: PathFilter,
    prefix: str,
    indent: str,
    last_sibling: bool,
) -> Iterator[str]:
    children = [c for c in entity.children() if filter(c)]
    if len(children) == 1:
        ancestors.append(entity)
        yield from tree_walk(
            children[0], ancestors, filter, prefix, indent, last_sibling
        )
        return

    line = ""
    line += prefix
    line += indent
    for ancestor in ancestors:
        line += ancestor.format().rstrip("/")
        line += "/"
    line += entity.format()
    yield line

    if prefix or indent:
        prefix += "    " if last_sibling else "│   "

    for child in children[:-1]:
        yield from tree_walk(child, [], filter, prefix, "├── ", False)
    for child in children[-1:]:
        yield from tree_walk(child, [], filter, prefix, "└── ", True)


def tree(entity: Entity, filter: PathFilter) -> Iterator[str]:
    yield from tree_walk(entity, [], filter, "", "", True)


def main(argv: list[str] | None = None):
    args = parse_args(argv)

    include = [PathMatch(expr) for expr in args.include.split("|") if expr.strip()]
    exclude = [PathMatch(expr) for expr in args.exclude.split("|") if expr.strip()]
    gitignore = make_ignore_parser() if args.gitignore else None
    filter = PathFilter(include=include, exclude=exclude, gitignore=gitignore)

    for path in args.paths:
        entity = Entity(path, preserve_path=True)
        for line in tree(entity, filter):
            print(line)


if __name__ == "__main__":
    main()
