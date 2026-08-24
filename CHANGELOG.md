# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-28

Initial release.

### Added

- `Config`/`Defaults`/`Rule` pydantic v2 models for parsing and validating
  `redirects.yml`, with `${VAR}` environment variable interpolation and
  validation errors that name the offending rule and field.
- `check()`: an async checker that fetches each rule's redirect chain
  (HEAD-first, falling back to GET on 405/501) with bounded concurrency, and
  asserts first-hop status, final URL, `max_hops`, no redirect loops, no
  https\-\>http downgrades, and that the final response isn't 4xx/5xx.
- `redirect-contract check <redirects.yml>` CLI command with
  `--format text|json|junit`, `--output`, `--basic-auth`, `--header`
  (repeatable), `--concurrency`, and `--no-color`. Exit codes: `0` pass,
  `1` assertion failure, `2` config/usage error.
- `record()` and `redirect-contract record`: probe a live site and emit a
  `redirects.yml` snapshot of its current redirect behaviour, so migrations
  can be verified snapshot-before / assert-after.
- Public Python API: `from redirect_contract import check, record, Config,
  Defaults, Rule, CheckReport, RuleResult, Hop, FailureReason`.

[0.1.0]: https://github.com/lkdmc/redirect-contract/releases/tag/v0.1.0
