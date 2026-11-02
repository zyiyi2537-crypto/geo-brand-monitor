"""Build a read-only GEO dashboard preview from an existing results.json.

The preview intentionally lives beside the source report and never overwrites
record.html. It is a presentation prototype for reviewing the proposed GEO
information architecture before changing the production renderer.
"""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
from pathlib import Path
from urllib.parse import urlsplit


ENGINE_NAMES = {
    "deepseek": "DeepSeek",
    "doubao": "豆包",
    "yuanbao": "元宝",
    "wenxin": "文心一言",
    "qwen": "通义千问",
}
ENGINE_ORDER = tuple(ENGINE_NAMES)


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def esc(value: object) -> str:
    return html.escape(text(value), quote=True)


def pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "—"
    return f"{numerator * 100 / denominator:.1f}%"


def source_domain(citation: dict) -> str:
    domain = text(citation.get("domain"))
    if domain:
        return domain
    try:
        return urlsplit(text(citation.get("url"))).netloc or "未知域名"
    except ValueError:
        return "未知域名"


def normalise(value: str) -> str:
    return "".join(value.lower().split())


def citation_state(verdict: dict, row: dict) -> str:
    status = text(verdict.get("citation_status"))
    if status == "cited" or verdict.get("matched_article_urls"):
        return "已引用"
    if status == "not_cited":
        return "未引用"
    collection = verdict.get("citation_collection") or row.get("citation_collection")
    if isinstance(collection, dict) and collection.get("complete") is False:
        return "待核查"
    return "待核查" if status in {"", "uncertain"} else status


def collection_state(verdict: dict, row: dict) -> str:
    collection = verdict.get("citation_collection") or row.get("citation_collection")
    if not isinstance(collection, dict):
        return "未报告"
    if collection.get("complete") is True:
        return "完整"
    if collection.get("complete") is False:
        return "不完整"
    return "未报告"


def build_payload(source: Path) -> dict:
    raw = json.loads(source.read_text(encoding="utf-8-sig"))
    config = raw.get("config") if isinstance(raw, dict) else {}
    brand = text(raw.get("brand")) or text(config.get("brand")) or "目标品牌"
    articles = config.get("articles") if isinstance(config, dict) else []
    articles = articles if isinstance(articles, list) else []
    article_urls = {text(item.get("url")) for item in articles if isinstance(item, dict)}
    rows: list[dict] = []
    question_numbers: dict[str, int] = {}
    questions = config.get("questions") if isinstance(config, dict) else []
    if isinstance(questions, list):
        question_numbers = {text(question): index for index, question in enumerate(questions, 1)}

    for item in raw.get("results", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        verdict = item.get("ai_verdict") if isinstance(item.get("ai_verdict"), dict) else {}
        answer = text(item.get("answer"))
        engine = text(item.get("engine"))
        brands = verdict.get("mentioned_brands")
        brands = brands if isinstance(brands, list) else []
        brand_entries = []
        target_rank = None
        aliases = {normalise(brand)}
        for entry in brands:
            if not isinstance(entry, dict):
                continue
            name = text(entry.get("name"))
            if not name:
                continue
            entry_aliases = entry.get("aliases")
            entry_aliases = entry_aliases if isinstance(entry_aliases, list) else []
            all_names = [name] + [text(alias) for alias in entry_aliases]
            is_target = any(normalise(alias) in aliases for alias in all_names if alias)
            brand_entries.append({
                "name": name,
                "aliases": [alias for alias in all_names if alias],
                "quote": text(entry.get("evidence_quote")),
                "is_target": is_target,
            })
            if is_target and target_rank is None:
                target_rank = len(brand_entries)
        citations = item.get("citations")
        citations = citations if isinstance(citations, list) else []
        clean_citations = []
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            clean_citations.append({
                "url": text(citation.get("url")),
                "title": text(citation.get("title")) or text(citation.get("url")),
                "domain": source_domain(citation),
                "position": citation.get("position"),
                "snippet": text(citation.get("snippet")),
            })
        matched = verdict.get("matched_article_urls")
        matched = matched if isinstance(matched, list) else []
        known_answer = bool(answer) and not text(item.get("error"))
        mention = verdict.get("brand_mentioned")
        mention = mention if isinstance(mention, bool) else None
        c_state = citation_state(verdict, item)
        rows.append({
            "question": text(item.get("query")),
            "question_no": question_numbers.get(text(item.get("query"))),
            "engine": engine,
            "engine_name": ENGINE_NAMES.get(engine, engine or "未知平台"),
            "answer": answer,
            "error": text(item.get("error")),
            "known_answer": known_answer,
            "brand_mentioned": mention,
            "brand_rank": target_rank,
            "brand_sentiment": text(verdict.get("brand_sentiment")),
            "citation_status": c_state,
            "collection_status": collection_state(verdict, item),
            "source_count": len(clean_citations),
            "matched_article_urls": [url for url in matched if isinstance(url, str)],
            "brands": brand_entries,
            "citations": clean_citations,
            "source_url": text(item.get("source_url")),
            "reason": text(verdict.get("reason")),
        })

    valid = [row for row in rows if row["known_answer"]]
    mention_known = [row for row in valid if row["brand_mentioned"] is not None]
    cited_known = [row for row in valid if row["citation_status"] != "待核查"]
    complete = [row for row in valid if row["collection_status"] == "完整"]
    target_mentions = [row for row in mention_known if row["brand_mentioned"] is True]
    target_citations = [row for row in cited_known if row["citation_status"] == "已引用"]
    ranked = [row["brand_rank"] for row in target_mentions if row["brand_rank"]]
    platform_rows = []
    for engine in ENGINE_ORDER:
        selected = [row for row in rows if row["engine"] == engine]
        selected_valid = [row for row in selected if row["known_answer"]]
        selected_mentions = [row for row in selected_valid if row["brand_mentioned"] is not None]
        selected_cited = [row for row in selected_valid if row["citation_status"] != "待核查"]
        ranks = [row["brand_rank"] for row in selected_mentions if row["brand_mentioned"] and row["brand_rank"]]
        platform_rows.append({
            "engine": engine,
            "name": ENGINE_NAMES[engine],
            "total": len(selected),
            "valid": len(selected_valid),
            "mention_count": sum(row["brand_mentioned"] is True for row in selected_mentions),
            "mention_total": len(selected_mentions),
            "citation_count": sum(row["citation_status"] == "已引用" for row in selected_cited),
            "citation_total": len(selected_cited),
            "complete_count": sum(row["collection_status"] == "完整" for row in selected_valid),
            "rank_avg": round(sum(ranks) / len(ranks), 1) if ranks else None,
            "source_avg": round(sum(row["source_count"] for row in selected_valid) / len(selected_valid), 1) if selected_valid else None,
        })

    brand_counts: dict[str, dict] = {}
    for row in valid:
        seen = set()
        for entry in row["brands"]:
            name = entry["name"]
            key = normalise(name)
            if not key or entry["is_target"] or key in seen:
                continue
            seen.add(key)
            item = brand_counts.setdefault(key, {"name": name, "count": 0, "questions": set(), "platforms": Counter()})
            item["count"] += 1
            item["questions"].add(row["question"])
            item["platforms"][row["engine_name"]] += 1
    brand_ranking = [{
        "name": item["name"],
        "count": item["count"],
        "question_count": len(item["questions"]),
        "platforms": dict(item["platforms"]),
    } for item in sorted(brand_counts.values(), key=lambda item: (-item["count"], item["name"]))]

    question_ranking = []
    for question in sorted({row["question"] for row in target_mentions}, key=lambda value: question_numbers.get(value, 999)):
        selected = [row for row in target_mentions if row["question"] == question]
        ranks_for_question = [row["brand_rank"] for row in selected if row["brand_rank"]]
        question_ranking.append({
            "question_no": question_numbers.get(question),
            "question": question,
            "rank_avg": round(sum(ranks_for_question) / len(ranks_for_question), 1) if ranks_for_question else None,
            "best_rank": min(ranks_for_question) if ranks_for_question else None,
            "platform_count": len(selected),
            "cited_count": sum(row["citation_status"] == "已引用" for row in selected),
        })
    question_ranking.sort(key=lambda item: (item["best_rank"] is None, item["best_rank"] or 999, item["question_no"] or 999))

    article_titles = {text(item.get("url")): text(item.get("title")) or f"目标文章 {index}"
                      for index, item in enumerate(articles, 1) if isinstance(item, dict)}
    article_counts = {url: {"title": title, "platforms": set(), "count": 0}
                      for url, title in article_titles.items()}
    for row in valid:
        for url in row["matched_article_urls"]:
            if url not in article_counts:
                article_counts[url] = {"title": url, "platforms": set(), "count": 0}
            article_counts[url]["platforms"].add(row["engine_name"])
            article_counts[url]["count"] += 1
    article_ranking = [{
        "title": item["title"],
        "url": url,
        "platform_count": len(item["platforms"]),
        "count": item["count"],
    } for url, item in sorted(article_counts.items(), key=lambda entry: (-entry[1]["count"], entry[0]))]

    domains = Counter()
    for row in valid:
        for citation in row["citations"]:
            domains[citation["domain"]] += 1
    source_ranking = [{"domain": domain, "count": count} for domain, count in domains.most_common(20)]

    generated_at = text(raw.get("generated_at")) if isinstance(raw, dict) else ""
    return {
        "brand": brand,
        "generated_at": generated_at,
        "completed_questions": raw.get("completed_questions", 0) if isinstance(raw, dict) else 0,
        "total_questions": raw.get("total_questions", len(question_numbers)) if isinstance(raw, dict) else len(question_numbers),
        "run_error": text(raw.get("run_error")) if isinstance(raw, dict) else "",
        "articles": [{"title": text(item.get("title")) or f"目标文章 {index}", "url": text(item.get("url"))} for index, item in enumerate(articles, 1) if isinstance(item, dict)],
        "rows": rows,
        "platforms": platform_rows,
        "brand_ranking": brand_ranking,
        "question_ranking": question_ranking,
        "article_ranking": article_ranking,
        "source_ranking": source_ranking,
        "summary": {
            "total_rows": len(rows),
            "valid_answers": len(valid),
            "mention_count": len(target_mentions),
            "mention_total": len(mention_known),
            "citation_count": len(target_citations),
            "citation_total": len(cited_known),
            "complete_count": len(complete),
            "rank_avg": round(sum(ranked) / len(ranked), 1) if ranked else None,
            "top3_count": sum(rank <= 3 for rank in ranked),
        },
    }


def render(payload: dict, original_name: str = "record.html") -> str:
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    brand = esc(payload["brand"])
    summary = payload["summary"]
    run_status = "检测完成" if not payload["run_error"] else "检测中断"
    run_time = esc(payload["generated_at"].replace("T", " ")[:19])
    original_href = esc(original_name)
    platform_bars = []
    for platform in payload["platforms"]:
        mention_width = platform["mention_count"] / platform["mention_total"] * 100 if platform["mention_total"] else 0
        citation_width = platform["citation_count"] / platform["citation_total"] * 100 if platform["citation_total"] else 0
        platform_bars.append(
            f'<div class="bar-row"><div class="bar-label">{esc(platform["name"])}</div><div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{mention_width:.1f}%"></div></div>'
            f'<div class="bar-track" style="margin-top:5px"><div class="bar-fill green" style="width:{citation_width:.1f}%"></div></div></div>'
            f'<div class="bar-value">提及 {pct(platform["mention_count"], platform["mention_total"])}<br><span class="muted">引用 {pct(platform["citation_count"], platform["citation_total"])}</span></div></div>'
        )
    brand_rows = []
    for index, item in enumerate(payload["brand_ranking"], 1):
        platforms = ", ".join(item["platforms"])
        brand_rows.append(
            f'<tr><td class="num">{index}</td><td><strong>{esc(item["name"])}</strong></td>'
            f'<td class="num">{item["count"]}</td><td class="num">{pct(item["count"], summary["valid_answers"])}</td>'
            f'<td class="num">{item["question_count"]}/{payload["total_questions"]}</td><td>{esc(platforms)}</td></tr>'
        )
    source_total = sum(item["count"] for item in payload["source_ranking"])
    source_rows = [
        f'<tr><td class="num">{index}</td><td><strong>{esc(item["domain"])}</strong></td><td class="num">{item["count"]}</td><td class="num">{pct(item["count"], source_total)}</td></tr>'
        for index, item in enumerate(payload["source_ranking"], 1)
    ]
    colors = ["#2563eb", "#07865a", "#f59e0b", "#7048c8", "#0ea5e9", "#94a3b8"]

    def pie_parts(items: list[tuple[str, int]]) -> tuple[str, str, int]:
        total = sum(value for _, value in items)
        if not total:
            return "conic-gradient(#dbe2ec 0deg 360deg)", '<div class="empty">暂无数据</div>', 0
        start = 0.0
        stops = []
        legend = []
        for index, (label, value) in enumerate(items):
            end = start + value / total * 360
            color = colors[index % len(colors)]
            stops.append(f"{color} {start:.2f}deg {end:.2f}deg")
            legend.append(
                f'<div class="legend-row"><span class="legend-dot" style="background:{color}"></span>'
                f'<span class="legend-label">{esc(label)}</span><span class="legend-value">{value}（{pct(value, total)}）</span></div>'
            )
            start = end
        return f"conic-gradient({','.join(stops)})", "".join(legend), total

    platform_pie_items = [(platform["name"], platform["mention_count"])
                          for platform in payload["platforms"] if platform["mention_count"]]
    platform_pie_css, platform_legend, platform_pie_total = pie_parts(platform_pie_items)
    source_pie_items = [(item["domain"], item["count"]) for item in payload["source_ranking"][:5]]
    source_top_total = sum(value for _, value in source_pie_items)
    source_all_total = sum(item["count"] for item in payload["source_ranking"])
    if source_all_total > source_top_total:
        source_pie_items.append(("其他来源", source_all_total - source_top_total))
    source_pie_css, source_legend, source_pie_total = pie_parts(source_pie_items)
    question_rank_rows = []
    for index, item in enumerate(payload["question_ranking"], 1):
        rank = item["best_rank"] if item["best_rank"] is not None else "—"
        width = max(8, 100 - min((item["rank_avg"] or 10) - 1, 9) / 9 * 92) if item["rank_avg"] else 8
        question_rank_rows.append(
            f'<tr><td class="rank-number">{index}</td><td class="rank-question">{esc(item["question"])}'
            f'<div class="rank-bar"><span style="width:{width:.1f}%"></span></div></td>'
            f'<td class="num">{rank}</td><td class="num">{item["platform_count"]}</td><td class="num">{item["cited_count"]}</td></tr>'
        )
    article_rank_rows = []
    for index, item in enumerate(payload["article_ranking"], 1):
        title = f'<a href="{esc(item["url"])}" target="_blank" rel="noopener">{esc(item["title"])}</a>' if item["url"] else esc(item["title"])
        article_rank_rows.append(
            f'<tr><td class="rank-number">{index}</td><td class="rank-question">{title}</td>'
            f'<td class="num">{item["count"]}</td><td class="num">{item["platform_count"]}</td></tr>'
        )
    if not question_rank_rows:
        question_rank_rows.append('<tr><td colspan="5" class="empty">本次没有可排名的目标品牌提及</td></tr>')
    if not article_rank_rows:
        article_rank_rows.append('<tr><td colspan="4" class="empty">本次没有确认的目标文章引用</td></tr>')
    data_json = data_json.replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>{brand} · GEO 监测看板预览</title>
<style>
:root{{--bg:#f4f6fa;--surface:#fff;--surface-2:#f8fafc;--line:#e3e8f0;--text:#142033;--muted:#6f7d91;--blue:#2563eb;--blue-soft:#eef4ff;--green:#07865a;--green-soft:#e8f7f0;--amber:#b45309;--amber-soft:#fff5e8;--red:#c9352b;--red-soft:#fff0ee;--shadow:0 1px 2px rgba(15,23,42,.04),0 12px 28px -20px rgba(15,23,42,.28);--radius:10px;--sidebar:230px}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}}a{{color:var(--blue);text-decoration:none}}a:hover{{text-decoration:underline}}button,input,select{{font:inherit}}button{{cursor:pointer}}.shell{{display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr);min-height:100vh}}.side{{position:sticky;top:0;height:100vh;background:var(--surface);border-right:1px solid var(--line);padding:18px 14px;display:flex;flex-direction:column}}.brand{{display:flex;gap:10px;align-items:center;padding:4px 8px 18px;border-bottom:1px solid var(--line)}}.logo{{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#2563eb,#12a8c4);color:#fff;display:grid;place-items:center;font-weight:800}}.brand strong{{display:block;font-size:14px}}.brand span{{font-size:10px;color:var(--muted)}}.nav{{padding:16px 2px;display:grid;gap:3px}}.nav a{{display:block;padding:8px 10px;border-radius:7px;color:#526177;font-weight:550}}.nav a:hover,.nav a.active{{background:var(--blue-soft);color:var(--blue);text-decoration:none}}.side-note{{margin-top:auto;border-top:1px solid var(--line);padding:13px 8px;color:var(--muted);font-size:11px}}.main{{min-width:0}}.top{{background:var(--surface);border-bottom:1px solid var(--line);padding:20px 26px 16px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}h1{{margin:0;font-size:22px;letter-spacing:0}}.subtitle{{color:var(--muted);margin-top:4px}}.top-actions{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}.btn{{border:1px solid var(--line);background:var(--surface);border-radius:7px;padding:7px 10px;color:#425168;text-decoration:none}}.btn.primary{{background:var(--blue);border-color:var(--blue);color:#fff}}.pill{{display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:650;background:var(--green-soft);color:var(--green)}}.content{{max-width:1580px;margin:0 auto;padding:22px 26px 64px}}.section{{margin:0 0 26px;scroll-margin-top:16px}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:0 0 10px}}h2{{font-size:17px;margin:0}}.section-head p{{color:var(--muted);margin:3px 0 0}}.kpi-grid{{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:10px}}.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:13px 14px;box-shadow:var(--shadow);min-height:102px}}.kpi-label{{color:var(--muted);font-size:11px}}.kpi-value{{font-size:23px;font-weight:750;margin-top:8px;font-variant-numeric:tabular-nums}}.kpi-foot{{font-size:10px;color:var(--muted);margin-top:6px}}.grid-2{{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);gap:14px}}.panel{{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}}.panel-head{{padding:14px 16px 10px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.panel-title{{font-weight:700}}.panel-note{{font-size:11px;color:var(--muted);margin-top:2px}}.panel-body{{padding:14px 16px}}.bar-row{{display:grid;grid-template-columns:88px 1fr 74px;align-items:center;gap:10px;margin:11px 0}}.bar-label{{font-weight:600}}.bar-track{{height:8px;background:#edf1f6;border-radius:5px;overflow:hidden}}.bar-fill{{height:100%;background:var(--blue);border-radius:inherit}}.bar-fill.green{{background:var(--green)}}.bar-value{{text-align:right;font-variant-numeric:tabular-nums;color:#425168}}.stat-line{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:9px 0;gap:12px}}.stat-line:last-child{{border-bottom:0}}.stat-line span:first-child{{color:var(--muted)}}.stat-line strong{{font-variant-numeric:tabular-nums}}.table-wrap{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:900px}}th,td{{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-size:11px;color:#5f6c80;background:var(--surface-2);font-weight:700;white-space:nowrap;position:sticky;top:0;z-index:1}}td{{font-size:12px}}tbody tr:hover{{background:#fbfcfe}}.qcell{{min-width:270px;max-width:390px;font-weight:600}}.qno{{display:inline-block;color:#9aa6b6;font-size:10px;margin-right:6px}}.muted{{color:var(--muted)}}.num{{font-variant-numeric:tabular-nums}}.status{{display:inline-flex;align-items:center;gap:4px;border-radius:999px;padding:3px 7px;font-size:10px;font-weight:700;white-space:nowrap}}.yes{{background:var(--green-soft);color:var(--green)}}.no{{background:#f1f4f7;color:#657388}}.wait{{background:var(--amber-soft);color:var(--amber)}}.bad{{background:var(--red-soft);color:var(--red)}}.rank-target{{color:var(--blue);font-weight:750}}.target-row{{background:#f4f8ff}}.filters{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}.filters select,.filters input{{border:1px solid var(--line);background:var(--surface);border-radius:7px;padding:7px 9px;color:#425168}}.brand-table td:first-child{{font-weight:700}}.target-badge{{font-size:10px;color:var(--blue);background:var(--blue-soft);border-radius:5px;padding:3px 5px;margin-left:5px}}.details-list{{display:grid;gap:8px}}details{{border:1px solid var(--line);border-radius:8px;background:var(--surface)}}summary{{cursor:pointer;padding:10px 12px;font-weight:650;list-style:none}}summary::-webkit-details-marker{{display:none}}details[open] summary{{border-bottom:1px solid var(--line);background:var(--surface-2)}}.evidence{{padding:12px}}.evidence-grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(260px,.8fr);gap:12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9fc;border:1px solid var(--line);border-radius:7px;padding:11px;margin:0;font:12px/1.7 "Microsoft YaHei",sans-serif;max-height:420px;overflow:auto}}.source-list{{margin:0;padding-left:18px;max-height:360px;overflow:auto}}.source-list li{{padding:5px 0;border-bottom:1px solid #eef1f5}}.source-list small{{display:block;color:var(--muted);overflow-wrap:anywhere}}.empty{{padding:22px;text-align:center;color:var(--muted)}}.footnote{{color:var(--muted);font-size:11px;margin-top:10px}}@media(max-width:1180px){{.kpi-grid{{grid-template-columns:repeat(4,minmax(130px,1fr))}}.grid-2{{grid-template-columns:1fr}}}}@media(max-width:780px){{.shell{{display:block}}.side{{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}}.nav{{display:flex;overflow:auto;padding-bottom:2px}}.nav a{{white-space:nowrap}}.top{{padding:16px}}.content{{padding:16px 12px 48px}}.kpi-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.top-actions{{justify-content:flex-start}}}}
 .rank-grid{{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,.8fr);gap:14px}}.rank-table{{width:100%;min-width:0}}.rank-table th,.rank-table td{{padding:8px 9px}}.rank-number{{font-size:18px;font-weight:800;color:var(--blue);font-variant-numeric:tabular-nums}}.rank-question{{font-weight:600;max-width:520px}}.rank-bar{{height:6px;background:#edf1f6;border-radius:4px;overflow:hidden;margin-top:5px}}.rank-bar span{{display:block;height:100%;background:var(--blue);border-radius:inherit}}.pie-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.pie-panel{{display:flex;align-items:center;gap:22px;padding:18px}}.pie{{width:150px;height:150px;border-radius:50%;background:conic-gradient(#2563eb 0deg 180deg,#07865a 180deg 270deg,#f59e0b 270deg 360deg);position:relative;flex:none}}.pie::after{{content:"";position:absolute;inset:36px;border-radius:50%;background:var(--surface)}}.pie-center{{position:absolute;inset:0;display:grid;place-items:center;z-index:1;text-align:center;font-size:12px;font-weight:750;line-height:1.3}}.legend{{display:grid;gap:8px;min-width:0}}.legend-row{{display:flex;align-items:center;gap:7px;font-size:11px}}.legend-dot{{width:9px;height:9px;border-radius:50%;flex:none}}.legend-label{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.legend-value{{margin-left:auto;font-variant-numeric:tabular-nums;color:#425168}}@media(max-width:900px){{.rank-grid,.pie-grid{{grid-template-columns:1fr}}.pie-panel{{justify-content:center}}}}@media(max-width:560px){{.pie-panel{{align-items:flex-start;gap:12px;padding:14px}}.pie{{width:118px;height:118px}}.pie::after{{inset:28px}}}}
</style></head><body>
<div class="shell"><aside class="side"><div class="brand"><div class="logo">G</div><div><strong>GEO 监测中心</strong><span>看板预览版</span></div></div><nav class="nav"><a class="active" href="#overview">总览</a><a href="#platforms">平台表现</a><a href="#ranking">排名与构成</a><a href="#questions">问题明细</a><a href="#brands">品牌排名</a><a href="#sources">引用来源</a><a href="#evidence">回答证据</a></nav><div class="side-note">基于最近一次真实检测结果生成<br>原始报告保持不变</div></aside>
<main class="main"><header class="top"><div><h1>{brand} · GEO 监测看板</h1><div class="subtitle">最近一次检测 · {run_time} · {payload["completed_questions"]}/{payload["total_questions"]} 个问题已完成</div></div><div class="top-actions"><span class="pill">{esc(run_status)}</span><a class="btn" href="{original_href}" target="_blank">打开原始报告</a></div></header>
<div class="content">
<section class="section" id="overview"><div class="section-head"><div><h2>本次总览</h2><p>先看整体可见性，再下钻到平台、问题和证据。</p></div></div><div class="kpi-grid">
<div class="kpi"><div class="kpi-label">有效回答</div><div class="kpi-value">{summary["valid_answers"]}/{summary["total_rows"]}</div><div class="kpi-foot">成功取得回答</div></div>
<div class="kpi"><div class="kpi-label">目标品牌提及率</div><div class="kpi-value">{pct(summary["mention_count"], summary["mention_total"])}</div><div class="kpi-foot">{summary["mention_count"]}/{summary["mention_total"]} 条已完成判定</div></div>
<div class="kpi"><div class="kpi-label">目标文章引用率</div><div class="kpi-value">{pct(summary["citation_count"], summary["citation_total"])}</div><div class="kpi-foot">{summary["citation_count"]}/{summary["citation_total"]} 条已完成核查</div></div>
<div class="kpi"><div class="kpi-label">品牌平均推荐排名</div><div class="kpi-value">{summary["rank_avg"] if summary["rank_avg"] is not None else "—"}</div><div class="kpi-foot">数字越小越靠前</div></div>
<div class="kpi"><div class="kpi-label">进入前三</div><div class="kpi-value">{summary["top3_count"]}</div><div class="kpi-foot">目标品牌排名 ≤ 3</div></div>
<div class="kpi"><div class="kpi-label">来源完整率</div><div class="kpi-value">{pct(summary["complete_count"], summary["valid_answers"])}</div><div class="kpi-foot">完整来源 {summary["complete_count"]}/{summary["valid_answers"]}</div></div>
<div class="kpi"><div class="kpi-label">其他品牌数量</div><div class="kpi-value">{len(payload["brand_ranking"])}</div><div class="kpi-foot">按有效回答去重统计</div></div>
</div></section>
<section class="section grid-2" id="platforms"><div class="panel"><div class="panel-head"><div><div class="panel-title">平台提及率与引用率</div><div class="panel-note">蓝色为品牌提及，绿色为目标文章引用。</div></div></div><div class="panel-body">{"".join(platform_bars)}</div></div>
<div class="panel"><div class="panel-head"><div><div class="panel-title">本次数据状态</div><div class="panel-note">把“未提及”和“没有数据”分开。</div></div></div><div class="panel-body"><div class="stat-line"><span>检测问题</span><strong>{payload["total_questions"]}</strong></div><div class="stat-line"><span>平台结果</span><strong>{summary["total_rows"]}</strong></div><div class="stat-line"><span>有效回答</span><strong>{summary["valid_answers"]}</strong></div><div class="stat-line"><span>待核查引用</span><strong>{sum(row["citation_status"] == "待核查" for row in payload["rows"])}</strong></div><div class="stat-line"><span>回答失败</span><strong>{sum(bool(row["error"]) for row in payload["rows"])}</strong></div></div></div></section>
<section class="section" id="ranking"><div class="section-head"><div><h2>排名与构成</h2><p>把目标品牌在问题中的推荐位置、目标文章引用次数和平台构成放在同一处。</p></div></div><div class="rank-grid"><div class="panel"><div class="panel-head"><div><div class="panel-title">目标品牌问题排名</div><div class="panel-note">按目标品牌在回答正文中的最佳推荐位置排序，排名越小越靠前。</div></div></div><div class="table-wrap"><table class="rank-table"><thead><tr><th>排名</th><th>问题</th><th>最佳位次</th><th>提及平台</th><th>文章引用</th></tr></thead><tbody>{"".join(question_rank_rows)}</tbody></table></div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">目标文章引用排名</div><div class="panel-note">按确认引用次数排序。</div></div></div><div class="table-wrap"><table class="rank-table"><thead><tr><th>排名</th><th>目标文章</th><th>引用次数</th><th>平台数</th></tr></thead><tbody>{"".join(article_rank_rows)}</tbody></table></div></div></div></section>
<section class="section"><div class="pie-grid"><div class="panel"><div class="panel-head"><div><div class="panel-title">平台提及构成</div><div class="panel-note">按目标品牌被提及的有效回答数量统计。</div></div></div><div class="pie-panel"><div class="pie" style="background:{platform_pie_css}"><div class="pie-center">{platform_pie_total}<br><span class="muted">次提及</span></div></div><div class="legend">{platform_legend}</div></div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">引用来源构成</div><div class="panel-note">展示引用次数最多的来源，剩余归入其他。</div></div></div><div class="pie-panel"><div class="pie" style="background:{source_pie_css}"><div class="pie-center">{source_pie_total}<br><span class="muted">条来源</span></div></div><div class="legend">{source_legend}</div></div></div></div></section>
<section class="section" id="questions"><div class="section-head"><div><h2>问题 × 平台明细</h2><p>目标品牌是否提及、品牌排名、文章引用和来源完整性分列展示。</p></div><div class="filters"><input id="qSearch" type="search" placeholder="搜索问题"><select id="engineFilter"><option value="all">全部平台</option>{"".join(f'<option value="{esc(e)}">{esc(ENGINE_NAMES[e])}</option>' for e in ENGINE_ORDER)}</select><select id="stateFilter"><option value="all">全部状态</option><option value="mention">已提及</option><option value="not_mention">未提及</option><option value="cited">已引用</option><option value="wait">待核查</option><option value="error">回答失败</option></select></div></div><div class="panel"><div class="table-wrap"><table id="questionTable"><thead><tr><th>问题</th><th>平台</th><th>目标品牌</th><th>品牌排名</th><th>提及位置</th><th>目标文章</th><th>来源完整性</th><th>来源数</th><th>状态</th></tr></thead><tbody id="questionBody"></tbody></table></div><div class="footnote" style="padding:0 14px 13px">点击下方“回答证据”查看完整回答、品牌识别依据和引用来源。</div></div></section>
<section class="section" id="brands"><div class="section-head"><div><h2>品牌提及排名</h2><p>目标品牌单独列出，并与其他品牌按有效回答中的出现次数比较。</p></div></div><div class="panel"><div class="table-wrap"><table class="brand-table"><thead><tr><th>排名</th><th>品牌</th><th>提及回答数</th><th>提及率</th><th>问题覆盖</th><th>主要平台</th></tr></thead><tbody><tr class="target-row"><td class="rank-target">目标</td><td><strong>{brand}</strong><span class="target-badge">目标品牌</span></td><td class="num">{summary["mention_count"]}</td><td class="num">{pct(summary["mention_count"], summary["mention_total"])}</td><td class="num">{len({row["question"] for row in payload["rows"] if row["brand_mentioned"] is True})}/{payload["total_questions"]}</td><td>—</td></tr>{"".join(brand_rows)}</tbody></table></div></div></section>
<section class="section" id="sources"><div class="section-head"><div><h2>引用来源排名</h2><p>查看 AI 实际使用了哪些域名，目标文章引用在问题详情里保留。</p></div></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>排名</th><th>来源域名</th><th>引用次数</th><th>占已采集来源</th></tr></thead><tbody>{"".join(source_rows) or '<tr><td colspan="4" class="empty">暂无已采集引用来源</td></tr>'}</tbody></table></div></div></section>
<section class="section" id="evidence"><div class="section-head"><div><h2>回答证据</h2><p>原始回答保持可追溯，但默认收起，避免长文本淹没结论。</p></div></div><div class="details-list" id="evidenceList"></div></section>
<div class="footnote">预览版只改变报告呈现层，数据来源于最近一次 results.json；原始 record.html、record.md 和 results.json 均未覆盖。</div>
</div></main></div>
<script id="report-data" type="application/json">{data_json}</script>
<script>
const DATA = JSON.parse(document.getElementById('report-data').textContent);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const status = (label, kind) => `<span class="status ${{kind}}">${{label}}</span>`;
const mentionCell = row => row.brand_mentioned === true ? status('✓ 已提及','yes') : row.brand_mentioned === false ? status('× 未提及','no') : status('待核对','wait');
const citationCell = row => row.citation_status === '已引用' ? status('已引用','yes') : row.citation_status === '未引用' ? status('未引用','no') : status('待核查','wait');
const stateCell = row => row.error ? status('回答失败','bad') : row.known_answer ? status('已完成','yes') : status('无回答','wait');
const rows = DATA.rows;
function renderQuestions() {{
  const query = document.getElementById('qSearch').value.trim().toLowerCase();
  const engine = document.getElementById('engineFilter').value;
  const state = document.getElementById('stateFilter').value;
  const filtered = rows.filter(row => {{
    if (query && !row.question.toLowerCase().includes(query)) return false;
    if (engine !== 'all' && row.engine !== engine) return false;
    if (state === 'mention' && row.brand_mentioned !== true) return false;
    if (state === 'not_mention' && row.brand_mentioned !== false) return false;
    if (state === 'cited' && row.citation_status !== '已引用') return false;
    if (state === 'wait' && row.citation_status !== '待核查') return false;
    if (state === 'error' && !row.error) return false;
    return true;
  }});
  document.getElementById('questionBody').innerHTML = filtered.map(row => {{
    const position = row.brand_rank ? (row.brand_rank <= 3 ? '前段' : '主体/后段') : '—';
    return `<tr><td class="qcell"><span class="qno">${{String(row.question_no || '').padStart(2,'0')}}</span>${{esc(row.question)}}</td><td>${{esc(row.engine_name)}}</td><td>${{mentionCell(row)}}</td><td class="num">${{row.brand_rank || '—'}}</td><td>${{position}}</td><td>${{citationCell(row)}}</td><td>${{row.collection_status === '完整' ? status('完整','yes') : row.collection_status === '不完整' ? status('不完整','wait') : status('未报告','no')}}</td><td class="num">${{row.source_count}}</td><td>${{stateCell(row)}}</td></tr>`;
  }}).join('') || `<tr><td colspan="9" class="empty">没有符合当前筛选条件的结果</td></tr>`;
}}
function renderEvidence() {{
  document.getElementById('evidenceList').innerHTML = rows.map(row => {{
    const title = `${{String(row.question_no || '').padStart(2,'0')}} · ${{esc(row.question)}} · ${{esc(row.engine_name)}}`;
    const sources = row.citations.length ? `<ol class="source-list">${{row.citations.map(source => `<li><a href="${{esc(source.url)}}" target="_blank" rel="noopener">${{esc(source.title || source.url)}}</a><small>${{esc(source.domain)}}${{source.position ? ` · 第 ${{esc(source.position)}} 条` : ''}}</small></li>`).join('')}}</ol>` : `<div class="empty">没有已采集来源</div>`;
    const brandEvidence = row.brands.length ? row.brands.map(item => `${{esc(item.name)}}${{item.is_target ? '（目标品牌）' : ''}}${{item.quote ? `：${{esc(item.quote)}}` : ''}}`).join('<br>') : '未提取到品牌列表';
    return `<details><summary>${{title}} <span class="muted">· 目标品牌 ${{row.brand_mentioned === true ? '已提及' : row.brand_mentioned === false ? '未提及' : '待核对'}}</span></summary><div class="evidence"><div class="evidence-grid"><div><div class="panel-note">模型判定</div><p>${{mentionCell(row)}} &nbsp; ${{citationCell(row)}} &nbsp; ${{stateCell(row)}}</p><p class="muted">${{esc(row.reason || '暂无判定说明')}}</p><div class="panel-note">回答正文</div><pre>${{esc(row.answer || row.error || '暂无回答')}}</pre></div><div><div class="panel-note">识别到的品牌</div><p>${{brandEvidence}}</p><div class="panel-note">引用来源</div>${{sources}}</div></div></div></details>`;
  }}).join('');
}}
['qSearch','engineFilter','stateFilter'].forEach(id => document.getElementById(id).addEventListener('input', renderQuestions));
renderQuestions(); renderEvidence();
</script></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a GEO dashboard preview from results.json")
    parser.add_argument("--results", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.results)
    output = Path(args.output)
    output.write_text(render(build_payload(source)), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
