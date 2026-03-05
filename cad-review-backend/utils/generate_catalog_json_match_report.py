#!/usr/bin/env python3
"""
Generate a 1:1 catalog <-> extracted JSON matching report (HTML + JSON).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from database import SessionLocal
from models import Catalog
from services.dxf_service import process_dwg_files


@dataclass
class CatalogItem:
    id: str
    sheet_no: str
    sheet_name: str
    sort_order: int


def _normalize_text(value: str) -> str:
    s = (value or "").strip().lower()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return "".join(ch for ch in s if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff"))


def _extract_sheet_no_from_text(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"[A-Za-z]{1,3}\d{0,3}[.\-_]\d{1,3}[a-zA-Z]?",
        r"[A-Za-z]\d{1,4}[a-zA-Z]?",
        r"\d{2}[.\-_]\d{2}[a-zA-Z]?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(0)
    if "COVER" in (text or "").upper():
        return "COVER"
    return ""


def _score_sheet_no(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    rn = _normalize_text(recognized)
    cn = _normalize_text(catalog)
    if not rn or not cn:
        return 0.0
    if rn == cn:
        return 0.99
    if rn in cn or cn in rn:
        return 0.94
    return SequenceMatcher(None, rn, cn).ratio() * 0.9


def _score_sheet_name(recognized: str, catalog: str) -> float:
    if not recognized or not catalog:
        return 0.0
    if recognized == catalog:
        return 1.0

    rn = _normalize_text(recognized)
    cn = _normalize_text(catalog)
    if not rn or not cn:
        return 0.0
    if rn == cn:
        return 0.98
    if rn in cn or cn in rn:
        return 0.92
    return SequenceMatcher(None, rn, cn).ratio() * 0.9


def _pick_catalog_item(
    sheet_no: str,
    sheet_name: str,
    layout_name: str,
    catalog_items: List[CatalogItem],
    used_catalog_ids: set,
):
    # exact sheet_no match first
    if sheet_no:
        for item in catalog_items:
            if item.id in used_catalog_ids:
                continue
            if (item.sheet_no or "").strip() == sheet_no.strip():
                return item, 1.0, 1.0, 0.0

    best_item = None
    best_score = 0.0
    best_no_score = 0.0
    best_name_score = 0.0

    for item in catalog_items:
        if item.id in used_catalog_ids:
            continue

        no_score = _score_sheet_no(sheet_no, item.sheet_no or "")
        name_score = max(
            _score_sheet_name(sheet_name, item.sheet_name or ""),
            _score_sheet_name(layout_name, item.sheet_name or ""),
        )

        if sheet_no:
            score = max(no_score, no_score * 0.85 + name_score * 0.25)
            if no_score < 0.60 and name_score >= 0.85:
                score = max(score, name_score * 0.90)
            if no_score >= 0.90 and name_score >= 0.70:
                score += 0.03
        else:
            score = name_score * 0.95

        if score > best_score:
            best_item = item
            best_score = score
            best_no_score = no_score
            best_name_score = name_score

    threshold = 0.72 if sheet_no else 0.78
    if not best_item or best_score < threshold:
        return None, best_score, best_no_score, best_name_score

    return best_item, best_score, best_no_score, best_name_score


def _load_catalog(project_id: str) -> List[CatalogItem]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Catalog)
            .filter(Catalog.project_id == project_id, Catalog.status == "locked")
            .order_by(Catalog.sort_order.asc())
            .all()
        )
        return [
            CatalogItem(
                id=row.id,
                sheet_no=row.sheet_no or "",
                sheet_name=row.sheet_name or "",
                sort_order=row.sort_order or 0,
            )
            for row in rows
        ]
    finally:
        db.close()


def _build_html(report: Dict) -> str:
    summary = report["summary"]
    matched_rows = report["matched_rows"]
    extras = report["extras"]
    placeholders = report["placeholders"]

    def esc(s: str) -> str:
        return (
            str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    matched_trs = []
    for idx, row in enumerate(matched_rows, 1):
        is_cover = "封面" in (row["catalog_sheet_name"] or "") or (row["catalog_sheet_no"] or "").upper() == "COVER"
        cls = "cover" if is_cover else ""
        matched_trs.append(
            f"<tr class='{cls}'><td>{idx}</td><td>{esc(row['catalog_sheet_no'])}</td><td>{esc(row['catalog_sheet_name'])}</td>"
            f"<td>{esc(row['json_sheet_no'])}</td><td>{esc(row['json_layout_name'])}</td><td>{esc(row['json_dwg'])}</td>"
            f"<td>{row['score']:.3f}</td><td>{'✅封面' if is_cover else '✅匹配'}</td></tr>"
        )

    extra_trs = [
        f"<tr><td>{i+1}</td><td>{esc(x['json_sheet_no'])}</td><td>{esc(x['json_layout_name'])}</td><td>{esc(x['json_dwg'])}</td><td>{x['score']:.3f}</td></tr>"
        for i, x in enumerate(extras)
    ]

    placeholder_trs = [
        f"<tr><td>{i+1}</td><td>{esc(x['catalog_sheet_no'])}</td><td>{esc(x['catalog_sheet_name'])}</td><td>占位JSON</td></tr>"
        for i, x in enumerate(placeholders)
    ]

    return f"""<!doctype html>
<html lang='zh-CN'>
<head>
<meta charset='utf-8'/>
<title>目录-JSON 一对一匹配报告</title>
<style>
body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif; margin: 24px; color:#111; }}
.card {{ display:inline-block; min-width:180px; margin:8px 12px 8px 0; padding:12px 14px; border:1px solid #ddd; border-radius:10px; background:#fafafa; }}
.k {{ color:#666; font-size:13px; }}
.v {{ font-size:22px; font-weight:700; margin-top:4px; }}
.ok {{ color:#0a7a2f; }}
.warn {{ color:#b45309; }}
.bad {{ color:#b91c1c; }}
table {{ border-collapse: collapse; width:100%; margin-top:10px; }}
th, td {{ border:1px solid #e5e7eb; padding:8px 10px; font-size:13px; text-align:left; }}
th {{ background:#f3f4f6; }}
tr.cover {{ background:#ecfdf3; }}
.section {{ margin-top:22px; }}
.progress-wrap {{ margin-top:12px; width:420px; height:12px; border-radius:999px; background:#eee; overflow:hidden; }}
.progress-bar {{ height:100%; background:#16a34a; width:{summary['one_to_one_rate']:.2f}%; }}
</style>
</head>
<body>
<h1>目录-JSON 一对一匹配报告</h1>
<div class='k'>生成时间：{esc(report['generated_at'])}</div>
<div class='k'>目录项目ID：{esc(report['catalog_project_id'])}</div>

<div class='card'><div class='k'>目录条目</div><div class='v'>{summary['catalog_count']}</div></div>
<div class='card'><div class='k'>提取JSON</div><div class='v'>{summary['extracted_count']}</div></div>
<div class='card'><div class='k'>1:1匹配成功</div><div class='v ok'>{summary['matched_count']}</div></div>
<div class='card'><div class='k'>多余JSON</div><div class='v warn'>{summary['extra_json_count']}</div></div>
<div class='card'><div class='k'>占位JSON</div><div class='v {'bad' if summary['placeholder_count'] else 'ok'}'>{summary['placeholder_count']}</div></div>
<div class='card'><div class='k'>1:1完成率</div><div class='v'>{summary['one_to_one_rate']:.1f}%</div></div>

<div class='progress-wrap'><div class='progress-bar'></div></div>

<div class='section'>
<h2>一对一匹配明细（{summary['matched_count']}）</h2>
<table>
<thead><tr><th>#</th><th>目录图号</th><th>目录图名</th><th>JSON图号</th><th>JSON布局名</th><th>来源DWG</th><th>匹配分</th><th>状态</th></tr></thead>
<tbody>
{''.join(matched_trs)}
</tbody>
</table>
</div>

<div class='section'>
<h2>多余JSON（跳过，不入1:1）({summary['extra_json_count']})</h2>
<table>
<thead><tr><th>#</th><th>JSON图号</th><th>JSON布局名</th><th>来源DWG</th><th>参考分</th></tr></thead>
<tbody>
{''.join(extra_trs) if extra_trs else '<tr><td colspan="5">无</td></tr>'}
</tbody>
</table>
</div>

<div class='section'>
<h2>占位JSON（目录有但JSON缺失）({summary['placeholder_count']})</h2>
<table>
<thead><tr><th>#</th><th>目录图号</th><th>目录图名</th><th>补齐方式</th></tr></thead>
<tbody>
{''.join(placeholder_trs) if placeholder_trs else '<tr><td colspan="4">无</td></tr>'}
</tbody>
</table>
</div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-project-id", required=True)
    parser.add_argument("--dwg-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    catalog_items = _load_catalog(args.catalog_project_id)
    if not catalog_items:
        raise SystemExit("No locked catalog items found")

    dwg_paths = sorted(str(p.resolve()) for p in Path(args.dwg_dir).glob("*.dwg"))
    extracted = process_dwg_files(dwg_paths, project_id="report", output_dir=args.out_dir)

    # Keep deterministic order
    extracted_sorted = sorted(
        extracted,
        key=lambda x: (str(x.get("sheet_no") or ""), str(x.get("layout_name") or ""), str(x.get("dwg") or "")),
    )

    used_catalog_ids = set()
    matched_rows = []
    extras = []

    for row in extracted_sorted:
        sheet_no = str(row.get("sheet_no") or "")
        layout_name = str(row.get("layout_name") or "")
        sheet_name = str((row.get("data") or {}).get("sheet_name") or "")
        json_dwg = str(row.get("dwg") or "")

        # 多候选图号：JSON图号 + 布局名 + DWG文件名
        candidates = []
        for cand in [sheet_no, _extract_sheet_no_from_text(layout_name), _extract_sheet_no_from_text(json_dwg)]:
            c = (cand or "").strip()
            if c and c not in candidates:
                candidates.append(c)
        if not candidates:
            candidates = [""]

        best = (None, 0.0, 0.0, 0.0, "")
        for cand in candidates:
            m, s, ns, nms = _pick_catalog_item(
                sheet_no=cand,
                sheet_name=sheet_name,
                layout_name=layout_name,
                catalog_items=catalog_items,
                used_catalog_ids=used_catalog_ids,
            )
            # 优先有匹配项，其次看分
            if m and (best[0] is None or s > best[1]):
                best = (m, s, ns, nms, cand)
            elif best[0] is None and s > best[1]:
                best = (m, s, ns, nms, cand)

        matched, score, no_score, name_score, used_candidate = best

        if matched:
            used_catalog_ids.add(matched.id)
            matched_rows.append(
                {
                    "catalog_id": matched.id,
                    "catalog_sheet_no": matched.sheet_no,
                    "catalog_sheet_name": matched.sheet_name,
                    "catalog_sort_order": matched.sort_order,
                    "json_sheet_no": sheet_no,
                    "json_layout_name": layout_name,
                    "json_dwg": str(row.get("dwg") or ""),
                    "json_path": str(row.get("json_path") or ""),
                    "used_sheet_no_candidate": used_candidate,
                    "score": score,
                    "no_score": no_score,
                    "name_score": name_score,
                }
            )
        else:
            extras.append(
                {
                    "json_sheet_no": sheet_no,
                    "json_layout_name": layout_name,
                    "json_dwg": str(row.get("dwg") or ""),
                    "json_path": str(row.get("json_path") or ""),
                    "score": score,
                }
            )

    placeholders = []
    for item in catalog_items:
        if item.id in used_catalog_ids:
            continue
        placeholders.append(
            {
                "catalog_id": item.id,
                "catalog_sheet_no": item.sheet_no,
                "catalog_sheet_name": item.sheet_name,
                "catalog_sort_order": item.sort_order,
            }
        )

    matched_rows.sort(key=lambda x: x["catalog_sort_order"])
    placeholders.sort(key=lambda x: x["catalog_sort_order"])

    summary = {
        "catalog_count": len(catalog_items),
        "extracted_count": len(extracted_sorted),
        "matched_count": len(matched_rows),
        "extra_json_count": len(extras),
        "placeholder_count": len(placeholders),
        "one_to_one_rate": (len(matched_rows) / len(catalog_items) * 100.0) if catalog_items else 0.0,
        "is_one_to_one": len(matched_rows) == len(catalog_items) and len(placeholders) == 0,
    }

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "catalog_project_id": args.catalog_project_id,
        "summary": summary,
        "matched_rows": matched_rows,
        "extras": extras,
        "placeholders": placeholders,
    }

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"catalog_json_match_report_{ts}.json"
    html_path = out_dir / f"catalog_json_match_report_{ts}.html"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_build_html(report), encoding="utf-8")

    print(json.dumps({
        "summary": summary,
        "json_report": str(json_path),
        "html_report": str(html_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
