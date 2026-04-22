# Runtime Environment

## Python Selection

The runner requires Python 3.14+.

Resolution order:

1. Check explicit local venv paths:
   - `.venv/bin/python`
   - `venv/bin/python`
   - `.venv/Scripts/python.exe`
   - `venv/Scripts/python.exe`
2. Verify interpreter version before using it.
3. Use the local venv only if it satisfies Python 3.14+.
4. If local venv is older, use a compatible system launcher such as `py` on Windows and report that choice.

Do not report an unsupported interpreter failure as product behavior.

## Dependency/Preflight Interpretation

If runner preflight reports missing Python dependencies, classify the scenario as environment/tooling blocked in that execution context. Do not diagnose the target product from that result.

If both a compatible interpreter and required dependencies are unavailable, report that a valid runner environment must be prepared before scenario execution can be meaningful.

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
