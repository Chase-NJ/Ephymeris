"""Marks `tests` as a package so `tests.compiler.tgpaths` resolves.

`tests/compiler/` is a package already — it has to be, since its modules import
one shared path helper by name. Without this file pytest's basedir walk stops at
`tests/` and puts THAT on `sys.path`, so `tests.compiler...` only imports when
the current directory happens to be on the path too: `python -m pytest` works
and the bare `pytest` script does not. One empty file makes the documented
command the working one.
"""
