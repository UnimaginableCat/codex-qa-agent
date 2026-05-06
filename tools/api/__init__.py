"""API tooling package."""

__all__ = ["ApiRequestRunner", "build_runner"]


def __getattr__(name: str) -> object:
    if name in {"ApiRequestRunner", "build_runner"}:
        from .services import ApiRequestRunner, build_runner

        exports = {
            "ApiRequestRunner": ApiRequestRunner,
            "build_runner": build_runner,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
