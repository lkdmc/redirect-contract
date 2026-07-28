"""Output formatters for CheckReport: text, json, junit."""

from redirect_contract.formatters.json import format_json
from redirect_contract.formatters.junit import format_junit
from redirect_contract.formatters.text import format_text

__all__ = ["format_json", "format_junit", "format_text"]
