"""Database tooling package."""

__all__ = ["DatabaseQueryRunner", "build_runner"]


def __getattr__(name: str) -> object:
    if name in {"DatabaseQueryRunner", "build_runner"}:
        from .services import DatabaseQueryRunner, build_runner

        exports = {
            "DatabaseQueryRunner": DatabaseQueryRunner,
            "build_runner": build_runner,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
