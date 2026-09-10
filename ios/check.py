#!/usr/bin/env python3
"""Catch what can be caught without a Mac.

There is no Swift compiler in the Linux environment these sources are written
in, and there never can be a useful one: SwiftUI, SwiftData and UIKit are
closed Apple frameworks that exist only on Apple platforms. So every change to
this app is unverified until it reaches Xcode, and the failures that reach
Xcode have been dull ones — a missing import, an unbalanced brace — that cost a
whole build cycle each.

This closes the two gaps that are closeable:

  1. Real syntax checking, via a genuine Swift grammar rather than counting
     braces. Catches anything the parser can't make sense of, with a line
     number.
  2. Symbol resolution against SharedKit. A file using APIClient without
     importing SharedKit compiles fine in isolation and fails the moment Xcode
     links it — which is exactly what happened.

It cannot type-check. "Wrong argument label", "no such SF Symbol" and
"expression too complex" still need Xcode.

    pip install tree_sitter tree_sitter_swift
    python3 ios/check.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = ["ReelMap", "SharedKit", "ShareExtension"]


def _parser():
    try:
        import tree_sitter_swift
        from tree_sitter import Language, Parser
    except ImportError:
        sys.exit("Needs the parser: pip install tree_sitter tree_sitter_swift")
    return Parser(Language(tree_sitter_swift.language()))


def _first_error(node) -> tuple[int, str] | None:
    """Deepest ERROR/missing node, so the report points at the cause rather
    than the whole declaration containing it."""
    if node.type == "ERROR" or node.is_missing:
        return node.start_point[0] + 1, node.type
    if not node.has_error:
        return None
    for child in node.children:
        found = _first_error(child)
        if found:
            return found
    return node.start_point[0] + 1, node.type


def _shared_symbols() -> set[str]:
    out: set[str] = set()
    pattern = re.compile(
        r'public\s+(?:final\s+)?(?:struct|class|enum|actor|protocol)\s+(\w+)')
    for path in (ROOT / "SharedKit").glob("*.swift"):
        out.update(pattern.findall(path.read_text()))
    return out


def main() -> int:
    parser = _parser()
    shared = _shared_symbols()
    # Declared in the same module, so they need no import even though SharedKit
    # exports something with the same name.
    local = {"Place", "Match", "Point", "Period"}
    problems: list[str] = []
    checked = 0

    for target in TARGETS:
        for path in sorted((ROOT / target).rglob("*.swift")):
            checked += 1
            source = path.read_text()
            rel = path.relative_to(ROOT)

            tree = parser.parse(source.encode())
            if tree.root_node.has_error:
                line, kind = _first_error(tree.root_node) or (0, "?")
                problems.append(f"{rel}:{line}: syntax error near {kind}")

            if target == "SharedKit" or re.search(r'^import SharedKit$', source, re.M):
                continue
            body = re.sub(r'//[^\n]*', '', source)
            used = sorted(
                s for s in shared - local if re.search(rf'\b{s}\b', body)
            )
            if used:
                problems.append(
                    f"{rel}: uses {', '.join(used)} but never imports SharedKit")

    for line in problems:
        print(line)
    print(f"\n{checked} files checked, {len(problems)} problem(s).")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
