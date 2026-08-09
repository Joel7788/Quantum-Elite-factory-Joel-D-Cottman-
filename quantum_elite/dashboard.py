"""Neon post-dating telemetry dashboard: renders a run to standalone HTML."""

from __future__ import annotations

import html
from decimal import Decimal
from pathlib import Path

from .models import DealPacket, LeadStage
from .pipeline import PipelineResult
from .telemetry import EventStatus, StageEvent

# Neon post-dating palette; high-contrast on near-black.
PALETTE = {
    "background": "#05060a",
    "panel": "#0c1018",
    "cyan": "#00f0ff",
    "magenta": "#ff2ea6",
    "lime": "#39ff88",
    "amber": "#ffc857",
    "red": "#ff4d5e",
    "text": "#dfe7f5",
    "muted": "#6b7a99",
}

STATUS_COLORS = {
    EventStatus.OK: PALETTE["lime"],
    EventStatus.REJECTED: PALETTE["amber"],
    EventStatus.FAILED: PALETTE["red"],
}

HEALTH_COLORS = {
    "nominal": PALETTE["lime"],
    "degraded": PALETTE["red"],
    "idle": PALETTE["muted"],
}

STAGE_ORDER = tuple(LeadStage)


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def stylesheet() -> str:
    return f"""
    :root {{
      --bg: {PALETTE['background']};
      --panel: {PALETTE['panel']};
      --cyan: {PALETTE['cyan']};
      --magenta: {PALETTE['magenta']};
      --lime: {PALETTE['lime']};
      --amber: {PALETTE['amber']};
      --red: {PALETTE['red']};
      --text: {PALETTE['text']};
      --muted: {PALETTE['muted']};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 32px;
      background: radial-gradient(circle at 20% -10%, #131a2b 0%, var(--bg) 55%);
      color: var(--text);
      font-family: "SFMono-Regular", "JetBrains Mono", Menlo, Consolas, monospace;
    }}
    h1 {{
      margin: 0 0 4px; font-size: 26px; letter-spacing: 5px; color: var(--cyan);
      text-shadow: 0 0 8px var(--cyan), 0 0 24px rgba(0, 240, 255, 0.45);
    }}
    .subtitle {{ color: var(--magenta); letter-spacing: 3px; font-size: 12px; }}
    .grid {{
      display: grid; gap: 16px; margin: 24px 0;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    }}
    .card {{
      background: var(--panel); border: 1px solid rgba(0, 240, 255, 0.28);
      border-radius: 10px; padding: 16px;
      box-shadow: inset 0 0 22px rgba(0, 240, 255, 0.07);
    }}
    .card .label {{ color: var(--muted); font-size: 11px; letter-spacing: 2px; }}
    .card .value {{ font-size: 26px; margin-top: 6px; text-shadow: 0 0 10px currentColor; }}
    .pill {{
      display: inline-block; padding: 3px 10px; border-radius: 999px;
      border: 1px solid currentColor; font-size: 11px; letter-spacing: 1px;
    }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }}
    th {{
      text-align: left; color: var(--muted); font-weight: normal;
      letter-spacing: 2px; padding: 8px; border-bottom: 1px solid rgba(107, 122, 153, 0.4);
    }}
    td {{ padding: 8px; border-bottom: 1px solid rgba(107, 122, 153, 0.16); }}
    tr:hover td {{ background: rgba(0, 240, 255, 0.05); }}
    .bar {{
      height: 6px; border-radius: 3px; background: rgba(107, 122, 153, 0.22);
      overflow: hidden; margin-top: 6px;
    }}
    .bar > span {{
      display: block; height: 100%;
      background: linear-gradient(90deg, var(--cyan), var(--magenta));
      box-shadow: 0 0 12px var(--cyan);
    }}
    section {{ margin-top: 28px; }}
    section > h2 {{
      font-size: 13px; letter-spacing: 4px; color: var(--magenta);
      text-shadow: 0 0 8px rgba(255, 46, 166, 0.5); margin-bottom: 4px;
    }}
    footer {{ margin-top: 32px; color: var(--muted); font-size: 11px; letter-spacing: 1px; }}
    """


def _metric_card(label: str, value: str, color: str) -> str:
    return (
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value" style="color:{color}">{_esc(value)}</div></div>'
    )


def _stage_rows(result: PipelineResult) -> str:
    counts = result.telemetry.stage_counts()
    peak = max(counts.values(), default=0)
    rows = []
    for stage in STAGE_ORDER:
        count = counts.get(stage, 0)
        width = 0 if peak == 0 else int(round(100 * count / peak))
        rows.append(
            f"<tr><td>{_esc(stage.value)}</td><td>{count}</td>"
            f'<td><div class="bar"><span style="width:{width}%"></span></div></td></tr>'
        )
    return "".join(rows)


def _packet_rows(packets: tuple[DealPacket, ...]) -> str:
    rows = []
    for packet in packets:
        lead = packet.lead
        buyer = packet.assignment.buyer.name if packet.assignment else "unmatched"
        fee = _money(packet.assignment.fee) if packet.assignment else "--"
        offer = _money(packet.offer.amount) if packet.offer else "--"
        arv = _money(lead.underwriting.arv) if lead.underwriting else "--"
        color = PALETTE["lime"] if packet.is_closed_loop else PALETTE["amber"]
        rows.append(
            f"<tr><td>{_esc(lead.lead_id)}</td><td>{_esc(lead.address.one_line)}</td>"
            f"<td>{_esc(lead.motivation_score or '--')}</td><td>{_esc(arv)}</td>"
            f"<td>{_esc(offer)}</td><td>{_esc(buyer)}</td>"
            f'<td style="color:{color}">{_esc(fee)}</td>'
            f"<td>{len(packet.documents)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="8">no deals in this run</td></tr>'


def _event_rows(events: tuple[StageEvent, ...]) -> str:
    rows = []
    for event in events:
        color = STATUS_COLORS[event.status]
        rows.append(
            f'<tr><td>{_esc(event.at.strftime("%H:%M:%S"))}</td>'
            f"<td>{_esc(event.lead_id)}</td><td>{_esc(event.stage.value)}</td>"
            f'<td style="color:{color}">{_esc(event.status.value)}</td>'
            f"<td>{_esc(event.detail)}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="5">no telemetry recorded</td></tr>'


def render_dashboard(result: PipelineResult) -> str:
    """Render the full run as a standalone, dependency-free HTML document."""
    telemetry = result.telemetry
    health_color = HEALTH_COLORS[telemetry.health]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Quantum Elite Telemetry | Run {_esc(telemetry.run_id)}</title>
<style>{stylesheet()}</style>
</head>
<body>
<h1>QUANTUM ELITE FACTORY</h1>
<div class="subtitle">POST-DATING PROTOCOL // OPERATOR: JOEL D COTTMAN //
RUN {_esc(telemetry.run_id)}</div>
<div class="grid">
  {_metric_card("SYSTEM HEALTH", telemetry.health.upper(), health_color)}
  {_metric_card("LEADS INGESTED", str(len(result.packets)), PALETTE["cyan"])}
  {_metric_card("UNDER CONTRACT", str(len(result.contracted)), PALETTE["magenta"])}
  {_metric_card("ASSIGNED", str(len(result.assigned)), PALETTE["lime"])}
  {_metric_card("REJECTED", str(len(result.rejected)), PALETTE["amber"])}
  {_metric_card("PROJECTED FEES", _money(result.projected_revenue), PALETTE["lime"])}
  {_metric_card("RUNTIME (S)", str(telemetry.duration_seconds), PALETTE["cyan"])}
</div>
<section>
  <h2>STAGE THROUGHPUT</h2>
  <table><thead><tr><th>STAGE</th><th>COUNT</th><th>LOAD</th></tr></thead>
  <tbody>{_stage_rows(result)}</tbody></table>
</section>
<section>
  <h2>DEAL LEDGER</h2>
  <table><thead><tr><th>LEAD</th><th>PROPERTY</th><th>SCORE</th><th>ARV</th>
  <th>OFFER</th><th>BUYER</th><th>FEE</th><th>DOCS</th></tr></thead>
  <tbody>{_packet_rows(tuple(result.packets))}</tbody></table>
</section>
<section>
  <h2>EXECUTION TELEMETRY</h2>
  <table><thead><tr><th>TIME</th><th>LEAD</th><th>STAGE</th><th>STATUS</th>
  <th>DETAIL</th></tr></thead>
  <tbody>{_event_rows(tuple(telemetry.events))}</tbody></table>
</section>
<footer>
  Generated documents are drafts for attorney review. Nothing in this run signs
  or executes a contract.
</footer>
</body>
</html>
"""


def write_dashboard(result: PipelineResult, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dashboard(result))
    return path
