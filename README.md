# erd

A replacement for `tree` that does a few things differently.

## Usage

```
erd [-h|--help] | [<paths>...] [OPTIONS]
```

## Installation

```
pipx install .
```

Future work: self-contained executable

## Differences with `tree`

The output of `erd` is almost the same as `tree -aF --filesfirst`. However, it
has a few more differences:

### RC file support

`erd` checks `~/.config/erd.rc` for additional default command-line arguments.
Arguments specified in the RC file are prefixed onto the arguments provided, and
then parsed together with the rest of them.

A non-default RC file path can be set with `--rc=<path>`, or disabled entirely
with `--no-rc` or `--rc=`.

### Vertical compression

`erd` compresses single-entity directories onto the same line.

So instead of this:
```
a/
└── b/
    └── c
d/
└── e/
    ├── f
    └── g
```

`erd` gives you this:
```
a/b/c
d/e/
├── f
└── g
```

### Sort order

Symlinks to directories are treated as directories by `tree` for the sake of the
meta-sort operations. However, `erd` treats them as files.

So instead of this:
```
./
├── c
├── b@ -> ./a/
└── a/
```

`erd` gives you this:
```
./
├── b@ -> ./a/
├── c
└── a/
```

## FAQ

#### Q: What's the story behind the name?

A: It's a reference to the Erdtree from Elden Ring.
