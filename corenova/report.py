"""Verification report (HTML) — the human-readable twin of the Manifest."""

from __future__ import annotations

import html
import json
from typing import Any

CHECK_LABELS = {
    "compose_started": "Compose started",
    "container_healthy": "Container healthy",
    "health_check_passed": "Health check passed",
    "tests_passed": "Application tests",
    "screenshots_generated": "Screenshots captured",
    "screenshots_uploaded": "Screenshots published",
    "report_uploaded": "Report published",
    "verification_manifest_uploaded": "Manifest published",
    "required_platform_contract_valid": "Platform contract valid",
}

STYLE = """
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--ok:#16a34a;--bad:#dc2626;--brand:#2563eb}
*{box-sizing:border-box}body{margin:0;padding:32px;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",
Inter,Arial,sans-serif;color:#0f172a;background:#fff}h1{font-size:24px;margin:0 0 4px}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin:32px 0 12px}
.sub{color:#64748b;margin-bottom:24px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid #e2e8f0;vertical-align:top}
th{background:#f8fafc;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#475569}
code{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:13px;word-break:break-all}
.ok{color:#16a34a;font-weight:600}.bad{color:#dc2626;font-weight:600}
pre{background:#0b1220;color:#e2e8f0;padding:16px;border-radius:8px;overflow:auto;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}
.card{border:1px solid #e2e8f0;border-radius:10px;overflow:hidden}
.card img{width:100%;display:block}.card div{padding:10px 12px;font-size:13px;color:#475569}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600}
.pass{background:#f0fdf4;color:#16a34a}.fail{background:#fef2f2;color:#dc2626}
"""


def render(manifest: dict[str, Any], tests_output: str = "", log_tail: str = "") -> str:
    ev = manifest.get("_evidence") or {}
    checks = manifest["checks"]
    passed = all(checks.values())

    rows = "".join(
        f"<tr><td>{html.escape(CHECK_LABELS.get(k, k))}</td>"
        f"<td><code>checks.{html.escape(k)}</code></td>"
        f"<td class=\"{'ok' if v else 'bad'}\">{'Passed' if v else 'Failed'}</td></tr>"
        for k, v in checks.items()
    )
    shots = "".join(
        f"<div class=\"card\"><img src=\"{html.escape(s['url'])}\" alt=\"{html.escape(s['scenario'])}\"/>"
        f"<div><strong>{html.escape(s['scenario'])}</strong> · "
        f"{html.escape((s.get('caption') or {}).get('en',''))} / "
        f"{html.escape((s.get('caption') or {}).get('zh',''))}</div></div>"
        for s in manifest["artifacts"]["screenshots"]
    )
    assertion = ev.get("version_assertion") or {}
    probe = ev.get("health_probe") or {}

    def yn(v: Any) -> str:
        return f'<span class="ok">{html.escape(str(v))}</span>' if v else '<span class="bad">—</span>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Verification {html.escape(manifest['verification_id'])} · CoreNova Launch</title>
<style>{STYLE}</style></head>
<body>
<h1>Verification Report · {html.escape(manifest['app'])} {html.escape(manifest['app_version'])}</h1>
<div class="sub">
  <span class="badge {'pass' if passed else 'fail'}">{'PUBLISHED' if passed else 'NOT PUBLISHED'}</span>
  &nbsp; <code>{html.escape(manifest['verification_id'])}</code>
  &nbsp; verified_at {html.escape(manifest['verified_at'])}
</div>

<h2>Immutable inputs</h2>
<table>
<tr><th>App version</th><td><code>{html.escape(manifest['app_version'])}</code> ← release tag <code>{html.escape(manifest['release']['release_tag'])}</code> · source <code>{html.escape(manifest['release']['source_revision'][:12])}</code></td></tr>
<tr><th>Image (exact tag)</th><td><code>{html.escape(manifest['container']['image'])}</code></td></tr>
<tr><th>Image digest (linux/amd64)</th><td><code>{html.escape(manifest['container']['digest'])}</code></td></tr>
<tr><th>Index digest</th><td><code>{html.escape(manifest['container']['manifest_digest'])}</code></td></tr>
<tr><th>Pulled as</th><td><code>{html.escape((ev.get('pull_ref') or ''))}</code> via <code>{html.escape(str(ev.get('registry_host')))}</code></td></tr>
<tr><th>Platform contract</th><td><code>{html.escape(manifest['platform']['ami_id'])}</code> · {html.escape(manifest['platform']['region'])}/{html.escape(manifest['platform']['architecture'])} · source={html.escape(manifest['platform'].get('base_ami_source',''))} ({html.escape(manifest['platform']['platform_verification_id'])})</td></tr>
<tr><th>Config revisions</th><td>app <code>{html.escape(manifest['config']['app_config_revision'][:12])}</code> · compose <code>{html.escape(manifest['config']['compose_revision'][:12])}</code></td></tr>
<tr><th>Release type</th><td><code>{html.escape(manifest['website']['release']['type'])}</code> — {html.escape(manifest['website']['release']['type_evidence'])}</td></tr>
</table>

<h2>Publish gate</h2>
<table><thead><tr><th>Check</th><th>Field</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table>

<h2>Evidence</h2>
<table>
<tr><th>Health probe</th><td>HTTP {yn(probe.get('status'))} — {html.escape(str(probe.get('detail','')))}</td></tr>
<tr><th>Version assertion</th><td>{yn(assertion.get('ok'))} actual <code>{html.escape(str(assertion.get('actual','')))}</code> — {html.escape(str(assertion.get('detail','')))}</td></tr>
<tr><th>Tests</th><td>{html.escape(str(ev.get('tests','')))}</td></tr>
<tr><th>Container state</th><td><code>{html.escape(str(ev.get('container_state','')))}</code></td></tr>
<tr><th>Duration</th><td>{html.escape(str(ev.get('duration_s','')))}s（{html.escape(str(ev.get('started_at','')))} → {html.escape(str(ev.get('finished_at','')))}）</td></tr>
</table>

<h2>Screenshots</h2>
<div class="grid">{shots or '<em>none</em>'}</div>

<h2>Application test output</h2>
<pre>{html.escape(tests_output[-8000:] or '—')}</pre>

<h2>Container logs (tail)</h2>
<pre>{html.escape(log_tail[-8000:] or '—')}</pre>

<h2>Raw manifest</h2>
<pre>{html.escape(json.dumps({k: v for k, v in manifest.items() if not k.startswith('_')}, ensure_ascii=False, indent=2))}</pre>
</body></html>
"""
