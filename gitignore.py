import os
from dataclasses import dataclass
from functools import lru_cache

from lru import LruDict

"""
TODO:

* lru-dict dependency
    * https://pypi.org/project/lru-dict/

* Where to find pathspecs
    * man gitignore
        * .../.gitignore
        * $GIT_DIR/info/exclude
        * $(git config core.excludesFile) | $XDG_CONFIG_HOME/git/ignore | $HOME/.config/git/ignore
        * NOTE: The above order is important because the last rule wins.
        * NOTE: "Git does not follow symbolic links when accessing a .gitignore file in the working tree."
            * This only applies to the first case (.../.gitignore)

* How to turn pathspecs into regex patterns
    * https://git-scm.com/book/id/v2/Git-Internals-Environment-Variables#_pathspecs
    * https://pypi.org/project/pathspec/
        * https://github.com/cpburnz/python-pathspec/issues/38#issuecomment-1465084835
    * https://pypi.org/project/wcmatch/
    * NOTE: Patterns in local .gitignore files should have the repo-relative
      path to their parent dir injected before them.
    * NOTE: Patterns from //.gitignore and $GIT_DIR/info/exclude can be treated
      the same way if we consider the repo-relative path to be empty.
    * NOTE: Global ignore patterns should explicitly *NOT* have *ANY* prefix
"""


@lru_cache(1)
def git_root_ceilings() -> set[str]:
    ceilings = os.getenv("GIT_CEILING_DIRECTORIES", "").split(":")
    sym_ceilings, nonsym_ceilings = ceilings, []
    try:
        i = ceilings.index("")
        sym_ceilings, nonsym_ceilings = ceilings[:i], ceilings[i+1:]
    except ValueError:
        pass
    resolved_ceilings = {os.readlink(path) for path in sym_ceilings}
    resolved_ceilings.update(nonsym_ceilings)
    return resolved_ceilings


@lru_cache(1)
def git_root_override() -> str | None:
    git_work_tree = os.getenv("GIT_WORK_TREE")
    if git_work_tree:
        return git_work_tree

    git_dir = os.getenv("GIT_DIR")
    if git_dir:
        return os.path.dirname(git_dir)

    return None


@lru_cache(1)
def git_root_search_terminals() -> set[str]:
    terminals = {"/", os.path.expanduser("~")}
    terminals.update(git_root_ceilings())
    return terminals


class GitRootSearch:
    def __init__(self, cache_max_count=1024):
        self.override = git_root_override()
        self.terminals = git_root_search_terminals()
        self.find_root_cache: LruDict[str, str | None] = LruDict(cache_max_count)

    def find_root(self, start_dir: str) -> str | None:
        if self.override:
            return self.override
        return self._find_root(os.path.abspath(start_dir))

    def _find_root(self, d: str) -> str | None:
        if d in self.find_root_cache:
            return self.find_root_cache[d]

        if os.path.exists(os.path.join(d, ".git")):
            self.find_root_cache[d] = d
            return d

        if d in self.terminals:
            self.find_root_cache[d] = None
            return None

        return self._find_root(os.path.dirname(d))


@dataclass
class IgnoreRule:
    glob: str

    def append_to_pattern(self, accumulator: str) -> str:
        if self.glob.startswith("!"):
            # glob = self.glob[1:]
            # pattern = 
            # ignore, negate = wcmatch.glob.translate(
            #     [rule.pattern_glob for rule in self.ignore_rules],
            #     flags=wcmatch.glob.DOTGLOB | wcmatch.glob.GLOBSTAR,
            #     exclude=[rule.pattern_glob for rule in self.negate_rules],
            # )
            pass
        else:
            pass


@dataclass
class IgnoreRuleSet:
    rules: list[IgnoreRule]


@dataclass
class IgnoreRuleTree:
    nodes: dict[str, IgnoreRuleSet]


@dataclass
class IgnoreRuleForest:
    trees: dict[str, IgnoreRuleTree]
