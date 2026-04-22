# Runtime Environment

## Python Selection

The runner must be executed through the project/workspace venv. The venv must satisfy Python 3.14+.

Resolution order:

1. Check explicit local venv paths:
   - `.venv/bin/python`
   - `venv/bin/python`
   - `.venv/Scripts/python.exe`
   - `venv/Scripts/python.exe`
2. Verify interpreter version before using it.
3. Use the local venv only if it satisfies Python 3.14+ and has required dependencies.
4. If the local venv is missing, older than Python 3.14, or lacks dependencies, stop and report environment/tooling `BLOCKED`.
5. Use system `python` or `py` only if the user explicitly authorizes a non-venv fallback for this run.

Do not report an unsupported venv/interpreter failure as product behavior.

## Dependency/Preflight Interpretation

If runner preflight reports missing Python dependencies, classify the scenario as environment/tooling blocked in that execution context. Do not diagnose the target product from that result.

If the project venv is not runnable, report that a valid runner venv must be prepared before scenario execution can be meaningful.

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
