"""The quality report: plain text, one block per golden report."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evals.runner import AssetResult, ReportResult


def _asset_lines(asset: "AssetResult") -> list[str]:
    lines = [f"  asset {asset.step}"]
    for c in asset.checks:
        mark = "PASS" if c.passed else "FAIL"
        lines.append(f"    {mark} {c.check}" + (f": {c.detail}" if c.detail else ""))
    return lines


def _report_lines(result: "ReportResult") -> list[str]:
    lines = [f"{'PASS' if result.passed else 'FAIL'} {result.id} (campaign {result.status})"]
    for fact, found in result.key_facts.items():
        lines.append(f"  {'found' if found else 'missing'}: {fact}")
    for asset in ([result.research] if result.research else []) + result.assets:
        lines += _asset_lines(asset)
    return lines


def render(results: "list[ReportResult]") -> str:
    lines: list[str] = []
    for result in results:
        lines += _report_lines(result) + [""]
    failed = sum(not r.passed for r in results)
    lines.append(f"{failed} of {len(results)} reports failed")
    return "\n".join(lines) + "\n"
