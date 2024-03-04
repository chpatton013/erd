#!/usr/bin/env python3

import argparse
import fnmatch
import glob
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from typing import Iterator

import igittigitt.igittigitt
import wcmatch
from dircolors import Dircolors


XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
DEFAULT_RC_FILE = os.path.join(XDG_CONFIG_HOME, "erd.rc")
DIRCOLORS = Dircolors()


class GitignoreParser:
    ignore_rules: list[igittigitt.igittigitt.IgnoreRule] = []
    negate_rules: list[igittigitt.igittigitt.IgnoreRule] = []
    _patterns: tuple[re.Pattern, re.Pattern] | None = None

    def _compile_patterns(self) -> tuple[re.Pattern, re.Pattern]:
        self.ignore_rules = sorted(set(self.ignore_rules))
        self.negate_rules = sorted(set(self.negate_rules))
        ignore, negate = wcmatch.glob.translate(
            [rule.pattern_glob for rule in self.ignore_rules],
            flags=wcmatch.glob.DOTGLOB | wcmatch.glob.GLOBSTAR,
            exclude=[rule.pattern_glob for rule in self.negate_rules],
        )
        ignore = "|".join(ignore)
        negate = "|".join(negate)
        self._patterns = (re.compile(ignore), re.compile(negate))
        return self._patterns

    def match(self, file_path: str) -> bool:
        ignore, negate = self._patterns or self._compile_patterns()
        if re.match(ignore, file_path):
            return not bool(re.match(negate, file_path))
        return False

    def _add_rule(self, rule: igittigitt.igittigitt.IgnoreRule) -> None:
        self._patterns = None
        if rule.is_negation_rule:
            self.negate_rules.append(rule)
        else:
            self.ignore_rules.append(rule)

    def add_rule(self, pattern: str, base_dir: str) -> None:
        rules = igittigitt.igittigitt.igittigitt.get_rules_from_git_pattern(
            git_pattern=pattern,
            path_base_dir=base_dir,
        )
        for rule in rules:
            self._add_rule(rule)

    def parse_rule_file(self, rule_file: str, base_dir: str | None = None) -> None:
        base_dir = base_dir or os.path.dirname(rule_file)

        with open(rule_file, "r") as f:
            line_number = 0
            for line in f:
                line_number += 1
                line = line.rstrip("\n")
                rules = igittigitt.igittigitt.get_rules_from_git_pattern(
                    git_pattern=line,
                    path_base_dir=base_dir,
                    path_source_file=rule_file,
                    source_line_number=line_number,
                )
                for rule in rules:
                    self._add_rule(rule)

    def parse_rule_files(self, base_dir: str, add_default_patterns: bool = False) -> None:
        if add_default_patterns:
            config_home = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
            default_rule_file = os.path.join(config_home, "git", "gitignore")
            try:
                self.parse_rule_file(default_rule_file, base_dir)
            except FileNotFoundError:
                pass

        rule_files = sorted(glob.glob(f"{base_dir}/**/.gitignore", recursive=True))
        for rule_file in rule_files:
            if not self.match(rule_file) or True:
                self.parse_rule_file(rule_file)


def find_git_toplevel(base_dir: str) -> str | None:
    if os.path.exists(os.path.join(base_dir, ".git")):
        return base_dir
    if base_dir == "/":
        return None
    return find_git_toplevel(os.path.dirname(base_dir))


def make_ignore_parser(base_dir: str) -> GitignoreParser | None:
    top = find_git_toplevel(base_dir)
    if not top:
        return None
    parser = GitignoreParser()
    parser.parse_rule_files(base_dir=top, add_default_patterns=True)
    return parser


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
    gitignore: GitignoreParser | None

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
    parser.add_argument("--gitignore", dest="gitignore", action="store_true")
    parser.add_argument("--no-gitignore", dest="gitignore", action="store_false")
    parser.set_defaults(gitignore=False)
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
    if not argv:
        argv = sys.argv[1:]
    parser = make_argument_parser()
    rc_group = parser.add_mutually_exclusive_group()
    rc_group.add_argument("--rc", default=DEFAULT_RC_FILE)
    rc_group.add_argument("--no-rc", dest="rc", action="store_false")
    args = parser.parse_args(argv)

    argv = combine_argv_and_rc(args.rc, argv)
    parser = make_argument_parser()
    return parser.parse_args(argv)


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

    for path in args.paths:
        path = os.path.expanduser(path)
        entity = Entity(path, preserve_path=True)
        base_dir = path if os.path.isdir(path) else os.path.dirname(path)
        gitignore = make_ignore_parser(base_dir) if args.gitignore else None
        filter = PathFilter(include=include, exclude=exclude, gitignore=gitignore)
        for line in tree(entity, filter):
            print(line)


if __name__ == "__main__":
    main(sys.argv[1:])
