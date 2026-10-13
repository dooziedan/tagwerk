"""The app's modules import each other in one direction only: no circles.

Imports inside functions count too: they used to hide circles that made the code hard to follow
(undo in app/changes.py needing the modules that import app/changes.py).
"""

import ast
from pathlib import Path

APP = Path(__file__).parent.parent / "app"


def _module(path: Path) -> str:
    parts = path.relative_to(APP.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports() -> dict[str, set[str]]:
    """Which app modules each app module imports, anywhere in the file."""
    modules = {_module(p): p for p in APP.rglob("*.py")}
    found: dict[str, set[str]] = {}
    for name, path in modules.items():
        targets = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                targets |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets.add(node.module)
                targets |= {f"{node.module}.{a.name}" for a in node.names}
        found[name] = {t for t in targets if t in modules and t not in (name, "app")}
    return found


def _circle(imports: dict[str, set[str]]) -> list[str] | None:
    """One circle of imports, or None."""
    done: set[str] = set()

    def visit(name: str, path: list[str]) -> list[str] | None:
        if name in path:
            return path[path.index(name) :] + [name]
        if name in done:
            return None
        for target in sorted(imports[name]):
            if circle := visit(target, [*path, name]):
                return circle
        done.add(name)
        return None

    for name in sorted(imports):
        if circle := visit(name, []):
            return circle
    return None


def test_no_import_circles():
    circle = _circle(_imports())
    assert circle is None, "Import circle: " + " -> ".join(circle)


def test_the_check_finds_a_circle():
    assert _circle({"a": {"b"}, "b": {"c"}, "c": {"a"}}) == ["a", "b", "c", "a"]
    assert _circle({"a": {"b"}, "b": set()}) is None
