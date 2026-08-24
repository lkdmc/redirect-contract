# redirect-contract

[![CI](https://github.com/lkdmc/redirect-contract/actions/workflows/ci.yml/badge.svg)](https://github.com/lkdmc/redirect-contract/actions/workflows/ci.yml)

Assert that old URLs still redirect where you intended, as a YAML contract you can run in CI.

## The problem

When a website is restructured — a yearly course-site rollover, a docs
migration, a domain change — old URLs are supposed to keep working via
redirects. Nobody verifies this. Existing link checkers (like
[lychee](https://github.com/lycheeverse/lychee) or
[linkchecker](https://github.com/linkchecker/linkchecker)) only answer
*"is this link dead?"*, not *"does this old URL still land where I
intended?"* A redirect that used to go `/2024/files` → `/2024-files/` can
silently start pointing at a 404, a login page, or the wrong article, and a
plain link checker will report it as perfectly healthy — it's still a `200`
at the end of the chain.

`redirect-contract` lets you write down the redirects you expect as a small
YAML file, then assert them against the live site:

```bash
redirect-contract check redirects.yml
```

```
FAIL /2024/files
  expected: 301 -> /2024-files/
  actual:   301 -> /2024-files -> 301 -> /2024-files/  (2 hops)

PASS /old-page
PASS /

1/3 passed
```

Run it as a CI gate before and after a migration, and a broken redirect
becomes a failed pipeline instead of a support ticket three months later.

## Install

```bash
pip install redirect-contract
```

Requires Python 3.10+. (Not on PyPI yet? Install straight from a checkout:
`pip install .`, or `pip install -e ".[dev]"` for development.)

## Quickstart

Write down the redirects you expect in `redirects.yml`:

```yaml
version: 1
base_url: https://example.org
defaults:
  status: 301
  max_hops: 2
rules:
  - from: /2024/files
    to: /2024-files/
  - from: /old-page
    to: https://other.example.org/new-page
    status: 302
  - from: /
    to: /2026/
```

Then check it against the live site:

```bash
redirect-contract check redirects.yml
```

For each rule, `redirect-contract` requests `from` (HEAD first, falling back
to GET if the server rejects HEAD with `405`/`501`), follows the redirect
chain, and asserts:

- the first hop's status code matches `status`
- the chain resolves to exactly `to` (resolved against `base_url` if relative)
- the chain is no longer than `max_hops`
- there's no redirect loop
- the final response isn't `4xx`/`5xx`
- nothing in the chain downgrades `https` to `http`

Exit codes: `0` everything passed, `1` at least one rule failed, `2` the
config itself is invalid or the CLI was used wrong — so `redirect-contract
check` slots directly into a CI pipeline's pass/fail logic.

## YAML reference

```yaml
version: 1                        # required, currently always 1

base_url: https://example.org     # required; supports ${VAR} interpolation

defaults:                         # optional; every field below is optional
  status: 301                     # expected first-hop status. default: 301
  max_hops: 5                     # max redirects before failing. default: 5
  timeout: 10.0                   # per-request timeout in seconds. default: 10.0
  headers:                        # sent with every request
    X-Custom: value
  basic_auth: "${BASIC_USER}:${BASIC_PASS}"   # HTTP Basic Auth, "user:pass"

rules:
  - from: /2024/files              # required; must start with "/"
    to: /2024-files/                # required; a "/"-path (resolved against
                                     # base_url) or a full http(s) URL
    status: 301                     # overrides defaults.status for this rule
    max_hops: 2                     # overrides defaults.max_hops
    name: "2024 files rollover"     # optional label used in failure/report output
    headers:                        # merged over defaults.headers for this rule
      X-Custom: override
```

**Environment variables.** Any string value may reference `${VAR_NAME}`; it's
substituted from the process environment before the file is parsed. A
missing variable is a config error naming exactly which rule/field
referenced it — never a silent empty string.

## Auth

For sites behind HTTP Basic Auth or a bearer token, either put it in the
YAML (with `${VAR}` interpolation so no secret is ever committed) or pass it
on the command line, which takes precedence over the config:

```bash
redirect-contract check redirects.yml \
  --basic-auth "$BASIC_USER:$BASIC_PASS" \
  --header "Authorization: Bearer $TOKEN"
```

## Output formats

```bash
redirect-contract check redirects.yml --format text    # default; human-readable
redirect-contract check redirects.yml --format json    # structured report
redirect-contract check redirects.yml --format junit --output report.xml
```

`--format text` is colorized by default; pass `--no-color` for plain output
in CI logs (or write to `--output`, which is always plain). `--format junit`
produces a JUnit XML file that both GitHub Actions and GitLab CI can render
as a test report.

## `--record`: capturing current behaviour before a migration

Before restructuring a site, snapshot what it currently does:

```bash
redirect-contract record /2024/files /old-page / --base-url https://example.org > redirects.yml
```

This probes each path and writes a `redirects.yml` reflecting the *current*
redirect behaviour — the starting point for a migration, not a check against
one. After you've made your changes (new nginx config, new CMS, whatever),
run `redirect-contract check redirects.yml` against the live site to confirm
nothing broke.

To re-probe the paths already declared in an existing contract (e.g. to
refresh a snapshot, or verify a `record` → `check` round trip):

```bash
redirect-contract record --from-config redirects.yml --output redirects.snapshot.yml
```

Credentials passed via `--basic-auth`/`--header` authenticate the probe
requests only — they are never written into the recorded YAML.

## Using it as a library

```python
import asyncio
from redirect_contract import check, Config

config = Config.from_yaml_file("redirects.yml")
report = asyncio.run(check(config))

if not report.passed:
    for result in report.results:
        if not result.passed:
            print(result.rule.from_, result.failure_reason, result.message)
```

## CI

### GitHub Actions

```yaml
- name: Check redirects
  run: |
    pip install redirect-contract
    redirect-contract check redirects.yml --format junit --output redirect-report.xml

- name: Publish redirect report
  if: always()
  uses: mikepenz/action-junit-report@v4
  with:
    report_paths: redirect-report.xml
```

### GitLab CI

```yaml
check-redirects:
  script:
    - pip install redirect-contract
    - redirect-contract check redirects.yml --format junit --output redirect-report.xml
  artifacts:
    when: always
    reports:
      junit: redirect-report.xml
```

## Development

```bash
git clone https://github.com/lkdmc/redirect-contract.git
cd redirect-contract
pip install -e ".[dev]"

pytest -q            # tests never touch the network (respx-mocked)
ruff check .
ruff format --check .
mypy --strict src/
```

## Scope

Out of scope for v0.1, on purpose: crawling, sitemap discovery, HTML link
extraction, and a bundled GitHub Action wrapper. This tool checks the
redirects *you* declare, nothing more.

## License

[MIT](LICENSE)
