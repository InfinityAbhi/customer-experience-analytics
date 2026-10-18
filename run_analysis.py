"""Validate a sample survey CSV, query it with SQLite, and build a local dashboard.

Run: python3 run_analysis.py
This uses only the Python standard library and does not contact an AI service.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "survey-responses-1000.csv"
OUT = ROOT / "output"
EXPECTED = {"response_id", "submitted_at", "segment", "region", "nps", "nps_group", "satisfaction", "comment"}


def nps_group(score: int) -> str:
    return "Promoter" if score >= 9 else "Detractor" if score <= 6 else "Passive"


def classify_theme(comment: str) -> str:
    text = comment.lower()
    if "undo" in text:
        return "Undo discoverability"
    if "slow" in text or "big files" in text:
        return "Large-file speed"
    if "crash" in text:
        return "File crash"
    if "documentation" in text or "joins" in text:
        return "Documentation"
    if "export" in text:
        return "Export clarity"
    if "save my settings" in text:
        return "Settings persistence"
    return "Other"


def load_and_validate(path: Path) -> list[dict]:
    rows: list[dict] = []
    ids: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or []) != EXPECTED:
            raise ValueError(f"Unexpected CSV columns: {reader.fieldnames}")
        for line, raw in enumerate(reader, start=2):
            if not raw["response_id"] or raw["response_id"] in ids:
                raise ValueError(f"Missing or duplicate response ID at line {line}")
            ids.add(raw["response_id"])
            try:
                nps = int(raw["nps"])
                satisfaction = int(raw["satisfaction"])
                timestamp = datetime.fromisoformat(raw["submitted_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid score or timestamp at line {line}") from exc
            if not 0 <= nps <= 10 or not 1 <= satisfaction <= 5:
                raise ValueError(f"Out-of-range score at line {line}")
            if raw["nps_group"] != nps_group(nps):
                raise ValueError(f"NPS band disagrees with score at line {line}")
            if not raw["segment"] or not raw["region"]:
                raise ValueError(f"Missing segment/region at line {line}")
            comment = raw["comment"].strip()
            rows.append({
                "response_id": raw["response_id"],
                "submitted_at": timestamp.isoformat(),
                "survey_month": timestamp.strftime("%Y-%m"),
                "segment": raw["segment"],
                "region": raw["region"],
                "nps": nps,
                "nps_group": raw["nps_group"],
                "satisfaction": satisfaction,
                "comment": comment,
                "theme": classify_theme(comment),
            })
    if not rows:
        raise ValueError("Survey CSV is empty")
    return rows


def write_csv(path: Path, records: list[sqlite3.Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(records[0].keys())
        writer.writerows(tuple(record) for record in records)


def run_sql(rows: list[dict]) -> dict:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE responses (
        response_id TEXT PRIMARY KEY, submitted_at TEXT NOT NULL,
        survey_month TEXT NOT NULL, segment TEXT NOT NULL, region TEXT NOT NULL,
        nps INTEGER NOT NULL CHECK(nps BETWEEN 0 AND 10), nps_group TEXT NOT NULL,
        satisfaction INTEGER NOT NULL CHECK(satisfaction BETWEEN 1 AND 5),
        comment TEXT NOT NULL, theme TEXT NOT NULL
    )""")
    db.executemany("""INSERT INTO responses VALUES
        (:response_id, :submitted_at, :survey_month, :segment, :region,
         :nps, :nps_group, :satisfaction, :comment, :theme)""", rows)
    sql_blocks = [s.strip() for s in (ROOT / "analytics.sql").read_text().split(";") if s.strip()]
    names = ("overall", "segments", "themes", "monthly")
    results = {}
    for name, query in zip(names, sql_blocks, strict=True):
        result = db.execute(query).fetchall()
        results[name] = [dict(record) for record in result]
        write_csv(OUT / f"{name}.csv", result)
    # Independent Python calculation catches errors in either the SQL or data load.
    expected_nps = round(100 * sum((1 if r["nps"] >= 9 else -1 if r["nps"] <= 6 else 0) for r in rows) / len(rows), 1)
    expected_csat = round(100 * sum(r["satisfaction"] >= 4 for r in rows) / len(rows), 1)
    assert results["overall"][0]["nps"] == expected_nps
    assert results["overall"][0]["csat_top_two_pct"] == expected_csat
    db.close()
    return results


def make_dashboard(rows: list[dict], results: dict) -> None:
    # Keep only fields needed for filters and charts, no fake PII.
    public_rows = [{k: r[k] for k in ("segment", "region", "survey_month", "nps", "satisfaction", "comment", "theme")} for r in rows]
    data = json.dumps(public_rows, separators=(",", ":")).replace("<", "\\u003c")
    source_url = "https://exploremydata.com/datasets/survey-responses"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Customer Experience | NPS and CSAT Analysis</title>
<style>
:root {{ color-scheme: light; font-family: Inter, system-ui, -apple-system, sans-serif; background:#f4f7fb; color:#132238; }}
* {{ box-sizing:border-box; }} body {{ margin:0; }}
header {{ background:#102944; color:white; padding:38px max(5vw,24px) 34px; }}
header h1 {{ margin:5px 0 8px; font-size:clamp(29px,4vw,42px); letter-spacing:-.03em; }}
header p {{ margin:0; color:#d3e0ec; max-width:780px; line-height:1.5; }}
.eyebrow {{ text-transform:uppercase; letter-spacing:.17em; font-size:12px; font-weight:700; color:#70e0cd; }}
main {{ max-width:1200px; padding:25px; margin:auto; }}
.filterbar {{ display:flex; gap:15px; flex-wrap:wrap; background:white; border:1px solid #dce5ed; padding:18px; border-radius:14px; }}
label {{ display:flex; flex-direction:column; gap:7px; font-size:13px; font-weight:700; color:#3d536b; min-width:170px; }}
select {{ padding:10px 12px; border:1px solid #b7c7d6; border-radius:8px; background:#fff; color:#132238; font-size:15px; }}
.grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:16px 0; }}
.card,.panel {{ background:white; border:1px solid #dce5ed; border-radius:14px; padding:20px; box-shadow:0 3px 12px rgba(9,36,64,.035); }}
.card .label {{ color:#58718a; font-size:13px; font-weight:650; }} .card .value {{ font-size:34px; letter-spacing:-.04em; font-weight:750; margin:7px 0 2px; }}
.card .detail {{ font-size:12px; color:#6d8298; line-height:1.35; }}
.two {{ display:grid; grid-template-columns:1.15fr .85fr; gap:14px; }} .panel h2 {{ margin:0 0 6px; font-size:18px; }} .sub {{ margin:0 0 16px; color:#5e7187; font-size:13px; line-height:1.4; }}
.barrow {{ display:grid; grid-template-columns:112px 1fr 50px; gap:9px; align-items:center; margin:13px 0; font-size:13px; }}
.track {{ background:#e8eef4; border-radius:20px; height:13px; overflow:hidden; }} .fill {{ height:100%; border-radius:20px; background:#17a69a; min-width:2px; }}
.tablewrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; font-size:13px; }} th,td {{ padding:11px 8px; border-bottom:1px solid #e4ebf1; text-align:right; }} th:first-child,td:first-child {{ text-align:left; }} th {{ color:#58718a; font-size:12px; }}
.foot {{ font-size:13px; color:#4e657c; line-height:1.6; }} .foot a {{ color:#0a637a; }}
.tag {{ display:inline-block; font-size:11px; font-weight:700; color:#0c6d65; background:#dcf8f3; padding:4px 8px; border-radius:6px; margin-bottom:6px; }}
@media(max-width:800px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} .two {{ grid-template-columns:1fr; }} }}
@media(max-width:480px) {{ .grid {{ grid-template-columns:1fr; }} main {{ padding:15px; }} header {{ padding:30px 20px; }} }}
</style></head><body>
<header><div class="eyebrow">Customer experience analytics</div><h1>NPS and CSAT survey analysis</h1>
<p>Reproducible SQL and Python analysis of a 1,000-response, CC0 sample survey. Filter by customer segment and region to inspect recommendation, satisfaction, and text themes.</p></header>
<main><div class="filterbar"><label>Customer segment<select id="segment"></select></label><label>Region<select id="region"></select></label><label>Survey month<select id="month"></select></label></div>
<div class="grid" id="cards"></div>
<div class="two"><section class="panel"><h2>Recommendation bands</h2><p class="sub">Promoters 9-10, passives 7-8, detractors 0-6.</p><div id="bands"></div></section>
<section class="panel"><h2>Friction in detractor comments</h2><p class="sub">Rule-based themes from optional text; counts cover commenters only.</p><div id="themes"></div></section></div>
<div class="two" style="margin-top:14px"><section class="panel"><h2>Customer segments</h2><p class="sub">Descriptive NPS and top-two-box CSAT. Small cells should be interpreted cautiously.</p><div class="tablewrap" id="segments"></div></section>
<section class="panel"><h2>Monthly trend</h2><p class="sub">Submission-month view, not a longitudinal customer cohort.</p><div class="tablewrap" id="monthly"></div></section></div>
<section class="panel" style="margin-top:14px"><span class="tag">DATA AND INTERPRETATION</span><h2>What this analysis supports</h2>
<p class="foot">The survey is generated sample data, not actual customers or a company's business outcome. The source creates comments from a small repeated phrase pool and correlates satisfaction with NPS. The dashboard validates the analysis workflow and surfaces illustrative priorities. It does not establish causality, production adoption, or a measured improvement after a change.</p>
<p class="foot">CSAT uses ratings 4-5 as satisfied. NPS is percentage of promoters minus percentage of detractors. Blank comments are excluded from theme counts. Review the source <a href="{html.escape(source_url)}">dataset and CC0 license</a>, <a href="../analytics.sql">SQL</a>, and <a href="metrics.json">analysis output</a>.</p></section></main>
<script>
const rows={data};
const $=id=>document.getElementById(id);
function options(id,key){{ const vals=[...new Set(rows.map(r=>r[key]))].sort(); $(id).innerHTML='<option value="">All</option>'+vals.map(v=>`<option>${{v}}</option>`).join(''); }}
options('segment','segment'); options('region','region'); options('month','survey_month');
function nps(rr){{ return rr.length?100*rr.reduce((a,r)=>a+(r.nps>=9?1:r.nps<=6?-1:0),0)/rr.length:0; }}
function csat(rr){{ return rr.length?100*rr.filter(r=>r.satisfaction>=4).length/rr.length:0; }}
function number(n){{ return n.toLocaleString('en-US'); }}
function group(rr,key){{ return rr.reduce((acc,r)=>{{ (acc[r[key]]??=[]).push(r); return acc; }},{{}}); }}
function table(rr,key){{ const groups=group(rr,key); let t='<table><thead><tr><th>'+key.replace('_',' ')+'</th><th>Responses</th><th>NPS</th><th>CSAT</th></tr></thead><tbody>'; for(const [k,v] of Object.entries(groups).sort((a,b)=>a[0].localeCompare(b[0]))) t+=`<tr><td>${{k}}</td><td>${{number(v.length)}}</td><td>${{nps(v).toFixed(1)}}</td><td>${{csat(v).toFixed(1)}}%</td></tr>`; return t+'</tbody></table>'; }}
function bar(label,count,max){{ return `<div class="barrow"><span>${{label}}</span><div class="track"><div class="fill" style="width:${{Math.max(2,100*count/max)}}%"></div></div><strong>${{number(count)}}</strong></div>`; }}
function update(){{
 const rr=rows.filter(r=>(!$('segment').value||r.segment===$('segment').value)&&(!$('region').value||r.region===$('region').value)&&(!$('month').value||r.survey_month===$('month').value));
 const c=rr.filter(r=>r.comment), det=rr.filter(r=>r.nps<=6), p=rr.filter(r=>r.nps>=9), pass=rr.filter(r=>r.nps>=7&&r.nps<=8);
 const card=(l,v,d)=>`<div class="card"><div class="label">${{l}}</div><div class="value">${{v}}</div><div class="detail">${{d}}</div></div>`;
 $('cards').innerHTML=card('Survey responses',number(rr.length),'Validated 0-10 NPS and 1-5 satisfaction')+card('Net Promoter Score',nps(rr).toFixed(1),'Promoter % minus detractor %')+card('CSAT top-two box',csat(rr).toFixed(1)+'%','Ratings of 4 or 5')+card('Comment coverage',rr.length?(100*c.length/rr.length).toFixed(1)+'%':'0%','Optional free-text responses');
 $('bands').innerHTML=bar('Detractors',det.length,Math.max(rr.length,1))+bar('Passives',pass.length,Math.max(rr.length,1))+bar('Promoters',p.length,Math.max(rr.length,1));
 const themes=Object.entries(group(det.filter(r=>r.comment&&r.theme!=='Other'),'theme')).map(([t,v])=>[t,v.length]).sort((a,b)=>b[1]-a[1]);
 $('themes').innerHTML=themes.length?themes.map(([t,v])=>bar(t,v,Math.max(themes[0][1],1))).join(''):'<p class="sub">No matching detractor comments.</p>';
 $('segments').innerHTML=rr.length?table(rr,'segment'):'<p class="sub">No responses match these filters.</p>';
 $('monthly').innerHTML=rr.length?table(rr,'survey_month'):'<p class="sub">No responses match these filters.</p>';
 }}
['segment','region','month'].forEach(id=>$(id).addEventListener('change',update)); update();
</script></body></html>"""
    (OUT / "dashboard.html").write_text(page, encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = load_and_validate(SOURCE)
    results = run_sql(rows)
    source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    counts = Counter(r["theme"] for r in rows if r["nps"] <= 6 and r["comment"])
    summary = {
        "dataset": "ExploreMyData generated survey-response sample (CC0)",
        "source_url": "https://exploremydata.com/datasets/survey-responses",
        "source_sha256": source_sha,
        "response_count": len(rows),
        "unique_id_count": len({r["response_id"] for r in rows}),
        "score_band_mismatches": 0,
        "date_range": [min(r["submitted_at"] for r in rows), max(r["submitted_at"] for r in rows)],
        "overall": results["overall"][0],
        "segment_metrics": results["segments"],
        "top_detractor_themes": counts.most_common(5),
        "limitations": [
            "Generated sample responses, not observed customers or business performance.",
            "Comments are optional, repetitive and selected from score-linked phrase pools.",
            "Descriptive segment differences are not causal effects or implemented improvements.",
        ],
    }
    (OUT / "metrics.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    make_dashboard(rows, results)
    print(json.dumps({"responses": len(rows), "nps": summary["overall"]["nps"], "csat": summary["overall"]["csat_top_two_pct"], "dashboard": str(OUT / "dashboard.html")}, indent=2))


if __name__ == "__main__":
    main()
