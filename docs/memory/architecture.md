# Architecture

A composite GitHub Action. `action.yml` passes inputs to `send_email.py` through `env:`, and the
script POSTs one JSON request to Resend or Postmark with the Python standard library.

## Scripts

| Script      | Does                                                                |
| ----------- | ------------------------------------------------------------------- |
| `bin/setup` | `mise install` for the tools in `mise.toml`                         |
| `bin/lint`  | editorconfig-checker, shellcheck, shfmt, yamllint, actionlint, ruff |
| `bin/test`  | the `unittest` suite in `test/`. Offline, no credentials            |
| `bin/ci`    | setup, lint, test, in order                                         |

## Test tiers

- `bin/test` runs `send_email.py` in a subprocess with `test/stub/sitecustomize.py` on
  `PYTHONPATH`. The stub records each request and either answers 200 or forwards it to a fake
  provider on 127.0.0.1. `HTTPS_PROXY` points at a closed port as a backstop.
- CI runs `bin/ci`, then the action itself with `uses: ./` and hostile inputs against the same
  stub, then `test/check-action-call`. This covers the `action.yml` wiring, which only the
  Actions runtime can run.
- `.env.op` and `local/` send real email through 1Password references. They are manual only and
  never part of `bin/test` or CI.

## CI

One workflow, `.github/workflows/ci.yaml`, one job on `ubuntu-26.04`. Pull requests share a
concurrency group; pushes to `main` do not. No deploy: callers pin a release commit SHA.
