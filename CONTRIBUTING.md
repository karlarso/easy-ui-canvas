# Contributing

Issues are welcome: bug reports, questions and ideas.

External pull requests are not accepted for now. Pull requests are restricted to invited collaborators.

Collaborator workflow:

1. Create a branch from `main`.
2. Open a pull request against `main`.
3. The maintainer reviews and merges it; `main` is not pushed to directly.

## Running the tests

```bash
sh tests/run_all.sh
```

This runs the i18n consistency checks, the end-to-end server tests (temporary runtime and free ports), the snapshot API tests, the wheel-routing tests and, when the optional packages are present, the QR cross-check and the headless-browser smoke test. The tests need only the Python standard library and Node.js; the QR cross-check and the browser smoke test use the optional packages named in their headers and skip themselves when those are missing (a skip is not a failure). Please run the tests before opening a pull request. See [tests/README.md](tests/README.md).

Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
