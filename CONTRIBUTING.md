# Contributing

Start with a reproducible, sanitized input and the specific supported contract that failed. Describe expected behavior from pinned Helm/Kubernetes sources. Please discuss new reference families or lifecycle modes before implementing them; each needs controls for optionality, namespaces, external resources, and incomplete results.

Set up a venv, install `-e . build`, and run `python -m unittest discover -s tests -v`. Tests need no cluster. `scripts/verify_install.py` verifies a wheel/sdist outside the source tree. Optional historical corpus instructions are in `docs/DEMO.md`.

Do not submit Secret data, credentials, private chart renders, or copied upstream assets without provenance and license notices. Include a minimal control and documentation for a changed public contract. No auto-fix, telemetry, or live cluster access belongs in this alpha's scope.
