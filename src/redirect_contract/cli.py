"""The redirect-contract command-line interface."""

from __future__ import annotations

import asyncio
from enum import Enum
from pathlib import Path

import typer
from rich.console import Console

from redirect_contract.checker import check
from redirect_contract.exceptions import ConfigError, RecordError
from redirect_contract.formatters import format_json, format_junit, format_text
from redirect_contract.models import Config
from redirect_contract.record import record

app = typer.Typer(add_completion=False)


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
    junit = "junit"


@app.callback()
def main() -> None:
    """redirect-contract: assert that old URLs still redirect where you intended."""


@app.command("check")
def check_command(
    config_path: Path = typer.Argument(
        ..., exists=True, readable=True, dir_okay=False, help="Path to redirects.yml"
    ),
    output_format: OutputFormat = typer.Option(OutputFormat.text, "--format", help="Output format"),
    output: Path | None = typer.Option(
        None, "--output", help="Write output to a file instead of stdout"
    ),
    basic_auth: str | None = typer.Option(
        None, "--basic-auth", help="'user:pass' for HTTP Basic Auth, overrides the config's default"
    ),
    header: list[str] = typer.Option(
        [],
        "--header",
        help="Extra header as 'Key: Value', merged over each rule's headers (repeatable)",
    ),
    concurrency: int = typer.Option(10, "--concurrency", help="Max concurrent requests"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI color in text output"),
) -> None:
    """Check that every redirect rule in CONFIG_PATH still resolves as declared."""
    try:
        config = Config.from_yaml_file(config_path)
    except ConfigError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if basic_auth is not None and ":" not in basic_auth:
        typer.echo("--basic-auth must be in 'user:pass' format", err=True)
        raise typer.Exit(2)

    try:
        extra_headers = _parse_headers(header)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    report = asyncio.run(
        check(config, concurrency=concurrency, headers=extra_headers, basic_auth=basic_auth)
    )

    if output_format is OutputFormat.text:
        rendered = format_text(report, color=not no_color and output is None)
    elif output_format is OutputFormat.json:
        rendered = format_json(report)
    else:
        rendered = format_junit(report)

    if output is not None:
        output.write_text(rendered, encoding="utf-8")
    elif output_format is OutputFormat.text and not no_color:
        Console().print(rendered)
    else:
        typer.echo(rendered)

    raise typer.Exit(report.exit_code)


@app.command("record")
def record_command(
    paths: list[str] = typer.Argument(
        None,
        help="Paths to probe, e.g. /old-page /2024/files. "
        "Mutually exclusive with --from-config/--from-file.",
    ),
    from_config: Path | None = typer.Option(
        None,
        "--from-config",
        exists=True,
        readable=True,
        dir_okay=False,
        help="Reuse the `from` list and base_url of an existing redirects.yml",
    ),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        exists=True,
        readable=True,
        dir_okay=False,
        help="Read paths to probe from a file, one per line",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="Base URL of the live site to probe (required unless --from-config supplies one)",
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Write the recorded contract to a file instead of stdout"
    ),
    status: int = typer.Option(
        301, "--status", help="Baseline expected status written to defaults"
    ),
    max_hops: int = typer.Option(5, "--max-hops", help="Baseline max_hops written to defaults"),
    basic_auth: str | None = typer.Option(
        None,
        "--basic-auth",
        help="'user:pass' to authenticate the probe (never written to the output)",
    ),
    header: list[str] = typer.Option(
        [],
        "--header",
        help="Extra header as 'Key: Value' to authenticate the probe "
        "(repeatable, never written to the output)",
    ),
    concurrency: int = typer.Option(10, "--concurrency", help="Max concurrent requests"),
) -> None:
    """Probe a live site and emit a redirects.yml capturing its current redirect behaviour."""
    sources_given = sum(bool(source) for source in (paths, from_file, from_config))
    if sources_given != 1:
        typer.echo("Provide exactly one of: PATHS, --from-file, or --from-config", err=True)
        raise typer.Exit(2)

    resolved_base_url = base_url
    if from_config is not None:
        try:
            source_config = Config.from_yaml_file(from_config)
        except ConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        resolved_base_url = base_url or source_config.base_url
        resolved_paths = [rule.from_ for rule in source_config.rules]
    elif from_file is not None:
        resolved_paths = [
            line.strip()
            for line in from_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        resolved_paths = paths

    if not resolved_base_url:
        typer.echo("--base-url is required (unless --from-config supplies one)", err=True)
        raise typer.Exit(2)

    if basic_auth is not None and ":" not in basic_auth:
        typer.echo("--basic-auth must be in 'user:pass' format", err=True)
        raise typer.Exit(2)

    try:
        extra_headers = _parse_headers(header)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    try:
        recorded = asyncio.run(
            record(
                resolved_base_url,
                resolved_paths,
                status=status,
                max_hops=max_hops,
                headers=extra_headers,
                basic_auth=basic_auth,
                concurrency=concurrency,
            )
        )
    except RecordError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    rendered = recorded.to_yaml()
    if output is not None:
        output.write_text(rendered, encoding="utf-8")
    else:
        typer.echo(rendered)


def _parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"--header must be in 'Key: Value' format: {value!r}")
        key, _, val = value.partition(":")
        headers[key.strip()] = val.strip()
    return headers
