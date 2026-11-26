import dataclasses
import json
from collections import Counter
from collections.abc import Sequence
from importlib.metadata import version

from plancliff.fix import BROAD_FIX, Fix
from plancliff.scan import Finding, Verdict
from plancliff.settings import Settings
from plancliff.style import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, YELLOW, Style
from plancliff.verify import BEFORE, AFTER

FORMAT_VERSION = 1
SHOWN_VALUES = 6
INDENT = " " * 9
BADGES = {
    Verdict.CLIFF: (" CLIFF  ", "1;97;41"),
    Verdict.LATENT: (" LATENT ", "1;97;45"),
    Verdict.OK: (" ok     ", "1;32"),
    Verdict.ERROR: (" ERROR  ", "1;30;43"),
}
RATIO_STYLE = {Verdict.CLIFF: (BOLD, RED), Verdict.LATENT: (BOLD, MAGENTA), Verdict.OK: (DIM,)}
CALLS_BEFORE = f"calls {BEFORE.start + 1}-{BEFORE.stop}"


def _verification_line(finding: Finding, s: Style) -> str | None:
    v = finding.verification
    if finding.verification_error:
        return f"{s('could not verify:', YELLOW)} {finding.verification_error}"
    if v is None:
        return None
    after = f"calls {AFTER.start + 1}-{v.calls}"
    timings = f"{CALLS_BEFORE} {v.before_ms:.2f} ms, {after} {v.after_ms:.2f} ms"
    if v.confirmed:
        return f"{s('confirmed:', BOLD, RED)} Postgres switched to the generic plan at prepared call {v.switched_at} ({v.generic_plans}/{v.calls} generic); {timings}"
    if v.generic_plans == 0:
        return f"{s('not confirmed:', BOLD, MAGENTA)} Postgres kept the custom plan for {v.custom_plans}/{v.calls} calls in auto mode; {timings}"
    return f"{s('not confirmed:', BOLD, MAGENTA)} Postgres switched at prepared call {v.switched_at} but did not slow down enough; {timings}"


def _fix_line(fix: Fix, s: Style) -> str:
    if fix.error:
        return f"{s('fix ?', BOLD, YELLOW)} {fix.hint}\n{INDENT}      {s('could not be checked:', YELLOW)} {fix.error}"
    plans = f", {fix.generic_plans}/{fix.calls} generic" if fix.generic_plans is not None else ""
    result = f"calls {AFTER.start + 1}-{fix.calls} {fix.after_ms:.2f} ms{plans}"
    if fix.works:
        return f"{s('fix ✓', BOLD, GREEN)} {fix.hint}\n{INDENT}      {s('proven:', GREEN)} {result}"
    return f"{s('fix ✗', BOLD, RED)} {fix.hint}\n{INDENT}      {s('does not remove the cliff:', RED)} {result}"


def text_line(finding: Finding, s: Style) -> str:
    label, badge_style = BADGES[finding.verdict]
    badge = s(label, badge_style)
    if finding.verdict is Verdict.ERROR:
        return f"{badge} {s(finding.name, BOLD)}\n{INDENT}{s(finding.error, YELLOW)}"
    flagged = finding.verdict is not Verdict.OK
    ratio = s(f"{finding.ratio:8.1f}×", *RATIO_STYLE[finding.verdict])
    timings = f"{s('generic', DIM)} {finding.generic_ms:9.2f} ms{s(',', DIM)} {s('custom', DIM)} {finding.custom_ms:8.2f} ms"
    lines = [f"{badge} {ratio}  {timings}  {s(finding.name, BOLD) if flagged else finding.name}"]
    if flagged:
        values = finding.values
        shown = ", ".join(values[:SHOWN_VALUES]) + (f", … ({len(values)} values)" if len(values) > SHOWN_VALUES else "")
        lines.append(f"{INDENT}{s(f'triggered by the {finding.scenario} values:', DIM)} {s(shown, CYAN)}")
        verification = _verification_line(finding, s)
        if verification:
            lines.append(f"{INDENT}{verification}")
        lines.extend(f"{INDENT}{_fix_line(fix, s)}" for fix in finding.fixes)
    return "\n".join(lines)


def text_summary(counts: Counter, seconds: float, s: Style) -> str:
    def part(verdict: Verdict, *styles: str) -> str:
        text = f"{counts[verdict]} {verdict.value}"
        return s(text, *styles) if counts[verdict] else s(text, DIM)

    parts = [part(Verdict.CLIFF, BOLD, RED), part(Verdict.LATENT, BOLD, MAGENTA), part(Verdict.OK, GREEN), part(Verdict.ERROR, YELLOW)]
    summary = f"\n{sum(counts.values())} queries in {seconds:.1f} s: {', '.join(parts)}"
    if counts[Verdict.CLIFF]:
        summary += f"\n{s('Prefer the targeted fixes above to the broad one:', DIM)} {s(BROAD_FIX, DIM)}"
    return summary


def _rounded(value):
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    return value


def json_document(findings: Sequence[Finding], seconds: float, settings: Settings) -> str:
    """json_document renders a whole scan; FORMAT_VERSION changes whenever a field is renamed or removed."""
    counts = Counter(finding.verdict for finding in findings)
    document = {
        "format": FORMAT_VERSION,
        "plancliff": version("plancliff"),
        "settings": dataclasses.asdict(settings),
        "queries": [dataclasses.asdict(finding) for finding in findings],
        "summary": {"queries": len(findings), **{verdict.value: counts[verdict] for verdict in Verdict}, "seconds": seconds},
    }
    return json.dumps(_rounded(document), ensure_ascii=False, indent=2)
