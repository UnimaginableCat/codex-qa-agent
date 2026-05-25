# Runtime Environment

## Python Selection

The runner must be executed through the workspace-root venv. The venv must satisfy Python 3.14+.

Resolution order:

1. Check explicit workspace-root venv paths:
   - `.venv314/Scripts/python.exe`
   - `.venv/Scripts/python.exe`
   - `.venv314/bin/python`
   - `.venv/bin/python`
   Do not check or use `code/<project>/.venv*` for workspace runner/tooling commands.
2. Probe the public runner CLI needed for the request: `<candidate> -m tools.scenario_runner.batch_cli --help` for suites or `<candidate> -m tools.scenario_runner.cli --help` for one scenario. Store and reuse the first passing candidate.
3. Verify interpreter version before using it. A workspace venv may use a symlinked executable whose resolved path is outside the workspace; do not reject it from that path alone if the runner CLI guard accepts the active venv prefix.
4. Use the workspace-root venv only if it satisfies Python 3.14+ and has required dependencies.
5. If the workspace-root venv is missing, older than Python 3.14, or lacks dependencies, stop and report environment/tooling `BLOCKED`.
6. Use project venvs, system `python`, `python3`, `py`, or `uv run` only if the user explicitly authorizes a non-workspace fallback for this run.

Do not report an unsupported venv/interpreter failure as product behavior.

## Dependency/Preflight Interpretation

If runner preflight reports missing Python dependencies, classify the scenario as environment/tooling blocked in that execution context. Do not diagnose the target product from that result.

If the workspace-root venv is not runnable, report that a valid runner venv must be prepared before scenario execution can be meaningful.

## Network Checks

Run network checks from the same interpreter/environment that will execute the runner when:

- previous output failed on DNS or connection setup
- outbound access may be sandboxed/restricted
- the scenario depends on external API reachability

Check:

- `socket.gethostbyname(hostname)`
- `socket.getaddrinfo(hostname, port)`
- HTTPS probe with `requests.get(url, timeout=15, verify=False)`
- system resolver where available
- proxy variables and interpreter path

If DNS/HTTPS fail from the runner context, treat the result as environment-constrained unless independent evidence proves product failure.
