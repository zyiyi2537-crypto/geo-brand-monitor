"""Build a standalone, local-only GEO history trends page."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any
from unicodedata import normalize
from urllib.parse import quote, urlsplit


_ENGINES = ("deepseek", "doubao", "yuanbao", "wenxin", "qwen")
_ENGINE_NAMES = {
    "deepseek": "DeepSeek", "doubao": "豆包", "yuanbao": "元宝",
    "wenxin": "文心一言", "qwen": "通义千问",
}
_SENTIMENTS = {"positive": "正面", "neutral": "中性", "negative": "负面", "mixed": "褒贬混合"}
_DATE_FOLDER = re.compile(r"geo-record-(\d{8})-(\d{6})")


def _norm(value: str) -> str:
    return " ".join(normalize("NFKC", value).casefold().split())


def _parse_time(value: object, folder_name: str = "") -> datetime | None:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            pass
    match = _DATE_FOLDER.search(folder_name)
    if match:
        try:
            return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass
    return None


def _articles(config: object) -> tuple[str, ...]:
    if not isinstance(config, dict):
        return ()
    raw = config.get("articles")
    if not isinstance(raw, list):
        return ()
    urls: set[str] = set()
    for item in raw:
        value = item.get("url") if isinstance(item, dict) else item
        if isinstance(value, str) and value.strip():
            urls.add(value.strip())
    return tuple(sorted(urls))


def _brand(record: object) -> str:
    if not isinstance(record, dict):
        return ""
    value = record.get("brand")
    config = record.get("config")
    if not isinstance(value, str) and isinstance(config, dict):
        value = config.get("brand")
    return value.strip() if isinstance(value, str) else ""


def _record_question_names(data: dict[str, Any]) -> list[str]:
    config = data.get("config")
    raw = config.get("questions") if isinstance(config, dict) else None
    if isinstance(raw, list):
        configured = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
        if configured:
            return list(dict.fromkeys(configured))
    rows = data.get("results")
    if not isinstance(rows, list):
        return []
    return list(dict.fromkeys(
        row["query"].strip() for row in rows
        if isinstance(row, dict) and isinstance(row.get("query"), str) and row["query"].strip()
    ))


def _read_records(reports_root: str | Path) -> list[dict[str, Any]]:
    root = Path(reports_root)
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for folder in sorted(root.glob("geo-record-*")):
        path = folder / "results.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            records.append({
                "folder": folder.name, "time": _parse_time(None, folder.name),
                "brand": "", "data": {}, "questions": [], "articles": (),
                "rows": [], "read_error": f"结果文件无法读取：{type(exc).__name__}",
            })
            continue
        if not isinstance(data, dict):
            data = {}
        config = data.get("config")
        config = config if isinstance(config, dict) else {}
        rows = data.get("results")
        records.append({
            "folder": folder.name,
            "time": _parse_time(data.get("generated_at"), folder.name),
            "brand": _brand(data), "data": data,
            "questions": _record_question_names(data),
            "articles": _articles(config),
            "rows": [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else [],
            "read_error": None,
        })
    return sorted(records, key=lambda item: (item["time"] or datetime.min.replace(tzinfo=timezone.utc), item["folder"]))


def available_brands(reports_root: str | Path) -> list[str]:
    """Return known brands in the report archive, sorted for a picker."""
    labels: dict[str, str] = {}
    for record in _read_records(reports_root):
        brand = record["brand"]
        if brand:
            labels.setdefault(_norm(brand), brand)
    return sorted(labels.values(), key=lambda value: _norm(value))


def _verdict(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("error") or row.get("ai_error"):
        return None
    value = row.get("ai_verdict")
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("brand_mentioned"), bool):
        return None
    if value.get("citation_status") not in {"cited", "not_cited", "uncertain"}:
        return None
    return value


def _row_groups(record: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in record["rows"]:
        query = row.get("query")
        engine = row.get("engine")
        if isinstance(query, str) and engine in _ENGINES:
            # One saved answer per engine/query is expected; keep the first stable row.
            groups[_norm(query)].setdefault(engine, row)
    return groups


def _outcome(rows_by_engine: dict[str, dict[str, Any]]) -> str | None:
    verdicts = {engine: _verdict(row) for engine, row in rows_by_engine.items()}
    if any(v is not None and v["brand_mentioned"] is True
           and v["citation_status"] == "cited" for v in verdicts.values()):
        return "qualified"
    if all(engine in verdicts and verdicts[engine] is not None
           and verdicts[engine]["citation_status"] in {"cited", "not_cited"}
           for engine in _ENGINES):
        return "not_qualified"
    return None


def _execution_complete(record: dict[str, Any]) -> bool:
    data = record["data"]
    completed = data.get("completed_questions")
    total = data.get("total_questions")
    if isinstance(completed, int) and isinstance(total, int):
        return completed >= total and total > 0 and not data.get("run_error")
    if data.get("run_error") or not record["questions"]:
        return False
    groups = _row_groups(record)
    return all(all(engine in groups.get(_norm(question), {})
                   for engine in _ENGINES) for question in record["questions"])


def _coverage(record: dict[str, Any]) -> dict[str, int]:
    expected = len(record["questions"]) * len(_ENGINES)
    groups = _row_groups(record)
    present = [groups.get(_norm(question), {}).get(engine)
               for question in record["questions"] for engine in _ENGINES]
    answered = sum(bool(row and not row.get("error") and isinstance(row.get("answer"), str)
                        and row["answer"].strip()) for row in present)
    verdicts = sum(_verdict(row) is not None for row in present if row)
    collections = [_reference_collection(row) for row in present if row]
    complete = sum(item.get("complete") is True for item in collections)
    partial = sum(item.get("complete") is False for item in collections)
    unknown = expected - complete - partial
    return {"expected": expected, "answered": answered, "verdicts": verdicts,
            "citations_complete": complete, "citations_partial": partial,
            "citations_unknown": max(0, unknown)}


def _reference_collection(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("citation_collection")
    if not isinstance(value, dict):
        verdict = row.get("ai_verdict")
        value = verdict.get("citation_collection") if isinstance(verdict, dict) else None
    return value if isinstance(value, dict) else {}


def _eligible_outcomes(record: dict[str, Any], keyword: str | None = None) -> list[dict[str, Any]]:
    groups = _row_groups(record)
    output = []
    keyword_key = _norm(keyword) if keyword else None
    for question in record["questions"]:
        key = _norm(question)
        if keyword_key and keyword_key not in key:
            continue
        rows = groups.get(key, {})
        state = _outcome(rows)
        output.append({"question": question, "key": key, "rows": rows, "state": state})
    return output


def _format_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "时间未知"


def _short_date(value: datetime | None) -> str:
    return value.astimezone().strftime("%m-%d") if value else "未知"


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _source_site(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        host = parsed.hostname.casefold().rstrip(".")
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return None


def _query_coverage_text(record: dict[str, Any], item: dict[str, Any] | None = None) -> str:
    if item is None:
        coverage = _coverage(record)
    else:
        rows = [item["rows"].get(engine) for engine in _ENGINES]
        collections = [_reference_collection(row) for row in rows if row]
        coverage = {
            "answered": sum(bool(row and not row.get("error") and isinstance(row.get("answer"), str)
                                 and row["answer"].strip()) for row in rows),
            "verdicts": sum(_verdict(row) is not None for row in rows if row),
            "expected": len(_ENGINES),
            "citations_complete": sum(value.get("complete") is True for value in collections),
            "citations_partial": sum(value.get("complete") is False for value in collections),
        }
    return (f"回答 {coverage['answered']}/{coverage['expected']}，"
            f"有明确 AI 判定 {coverage['verdicts']}/{coverage['expected']}，"
            f"引用采集完整 {coverage['citations_complete']}/5，"
            f"不完整 {coverage['citations_partial']}/5")


def _batch_summary(record: dict[str, Any], keyword: str | None) -> dict[str, Any]:
    items = _eligible_outcomes(record, keyword)
    decided = [item for item in items if item["state"] in {"qualified", "not_qualified"}]
    positives = sum(item["state"] == "qualified" for item in decided)
    complete = _execution_complete(record)
    rate = positives / len(decided) * 100 if complete and decided else None
    models = _model_signature(record, items)
    return {
        "record": record, "items": items, "decided": len(decided),
        "qualified": positives, "rate": rate, "complete": complete,
        "unknown": len(items) - len(decided),
        "models": models,
    }


def _model_signature(record: dict[str, Any], items: list[dict[str, Any]]) -> tuple[tuple[str, str], ...] | None:
    found: dict[str, str] = {}
    for item in items:
        for engine, row in item["rows"].items():
            verdict = _verdict(row)
            model = verdict.get("model") if verdict else None
            if isinstance(model, str) and model.strip():
                found[engine] = model.strip()
    if not found:
        return None
    return tuple(sorted(found.items()))


def _line_chart(title: str, series: list[tuple[str, str, list[tuple[str, float]]]]) -> str:
    available_dates = sorted({label for _, _, points in series for label, _ in points})
    if not available_dates or not any(points for _, _, points in series):
        return '<p class="empty">暂无可比较数据。</p>'
    width, height = 760, 300
    left, right, top, bottom = 58, 18, 24, 66
    plot_w, plot_h = width - left - right, height - top - bottom
    x_for = {label: left + (plot_w / max(1, len(available_dates) - 1)) * i
             for i, label in enumerate(available_dates)}
    bits = [f'<svg class="trend-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{_e(title)}">']
    bits.append(f'<text x="{left}" y="15" class="chart-title">{_e(title)}</text>')
    for tick in (0, 25, 50, 75, 100):
        y = top + plot_h * (1 - tick / 100)
        bits.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="grid"/>')
        bits.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" class="axis">{tick}%</text>')
    for i, label in enumerate(available_dates):
        if len(available_dates) > 8 and i not in {0, len(available_dates) - 1} and i % 2:
            continue
        x = x_for[label]
        bits.append(f'<text x="{x:.1f}" y="{height-36}" text-anchor="middle" class="axis">{_e(label)}</text>')
    for name, color, points in series:
        if not points:
            continue
        coords = []
        for label, value in points:
            x = x_for[label]
            y = top + plot_h * (1 - max(0, min(100, value)) / 100)
            coords.append((x, y, label, value))
        point_string = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
        bits.append(f'<polyline points="{point_string}" fill="none" stroke="{color}" stroke-width="2.5"/>')
        for x, y, label, value in coords:
            bits.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}"><title>{_e(name)} · {_e(label)}：{value:.1f}%</title></circle>')
    bits.append('</svg>')
    legend = "".join(f'<span><i style="background:{color}"></i>{_e(name)}</span>'
                     for name, color, points in series if points)
    return "".join(bits) + (f'<div class="legend">{legend}</div>' if legend else "")


def _report_link(folder: str) -> str:
    return f'./{quote(folder, safe="")}/record.html'


def _event_for(record: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {"record": record, "item": item, "time": record["time"],
            "models": _model_signature(record, [item])}


def _rank_articles(event: dict[str, Any], targets: tuple[str, ...]) -> tuple[list[tuple[str, int, int]], str | None]:
    counts: dict[str, dict[str, set[str]]] = {
        url: {"engines": set(), "citations": set()} for url in targets
    }
    cited = 0
    mapping_complete = True
    for engine, row in event["item"]["rows"].items():
        verdict = _verdict(row)
        if not verdict or verdict.get("citation_status") != "cited":
            continue
        cited += 1
        pairs = verdict.get("matched_citations")
        if not isinstance(pairs, list):
            mapping_complete = False
            continue
        valid_pairs = 0
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            article = pair.get("article_url")
            citation = pair.get("citation_url")
            if article in counts and isinstance(citation, str) and citation.strip():
                counts[article]["engines"].add(engine)
                counts[article]["citations"].add(citation.strip())
                valid_pairs += 1
        # Legacy AI verdicts can name target articles without a citation mapping.
        if valid_pairs == 0:
            mapping_complete = False
    if not cited:
        return [], "没有可用于排名的 AI 引用判定"
    if not mapping_complete:
        return [], "历史数据缺少完整的 AI 文章与引用链接配对，排名不可用"
    ranked = sorted(
        ((url, len(value["engines"]), len(value["citations"]))
         for url, value in counts.items() if value["engines"]),
        key=lambda row: (-row[1], -row[2], row[0]),
    )
    return ranked, None


def _rank_sites(event: dict[str, Any]) -> list[tuple[str, int, int]]:
    counts: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"engines": set(), "citations": set()})
    for engine, row in event["item"]["rows"].items():
        citations = row.get("citations")
        if not isinstance(citations, list):
            continue
        for citation in citations:
            value = citation.get("url") if isinstance(citation, dict) else None
            site = _source_site(value)
            if site:
                counts[site]["engines"].add(engine)
                counts[site]["citations"].add(str(value).strip())
    return sorted(
        ((site, len(value["engines"]), len(value["citations"])) for site, value in counts.items()),
        key=lambda row: (-row[1], -row[2], row[0]),
    )


def _rank_table(title: str, old: list[tuple[str, int, int]] | None,
                new: list[tuple[str, int, int]], *, unavailable: str | None = None) -> str:
    if unavailable:
        return f'<h4>{_e(title)}</h4><p class="empty">{_e(unavailable)}</p>'
    if not new:
        return f'<h4>{_e(title)}</h4><p class="empty">本次达标回答未采集到可排名的来源。</p>'
    old_rank = {row[0]: index for index, row in enumerate(old or [], 1)}
    new_rank = {row[0]: index for index, row in enumerate(new, 1)}
    all_items = list(dict.fromkeys([row[0] for row in new] + [row[0] for row in (old or [])]))
    bits = [f'<h4>{_e(title)}</h4><table><thead><tr><th>来源</th><th>上次排名</th><th>本次排名</th><th>变化</th><th>平台数</th><th>引用链接数</th></tr></thead><tbody>']
    current_map = {row[0]: row for row in new}
    for label in all_items:
        previous = old_rank.get(label)
        current = new_rank.get(label)
        if current is not None and previous is None:
            movement = "新增"
        elif current is None:
            movement = "本次未进入排名"
        elif previous is not None and current < previous:
            movement = f"上升 {previous-current} 位"
        elif previous is not None and current > previous:
            movement = f"下降 {current-previous} 位"
        else:
            movement = "持平"
        platforms, citations = (current_map[label][1:] if current is not None else ("—", "—"))
        bits.append(f'<tr><td>{_e(label)}</td><td>{previous if previous is not None else "—"}</td>'
                    f'<td>{current if current is not None else "—"}</td><td>{_e(movement)}</td>'
                    f'<td>{platforms}</td><td>{citations}</td></tr>')
    bits.append('</tbody></table>')
    return "".join(bits)


def _assessment(event: dict[str, Any]) -> str:
    sentiments: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    evidence_rows: list[str] = []
    for engine, row in event["item"]["rows"].items():
        verdict = _verdict(row)
        if not verdict or verdict.get("brand_mentioned") is not True:
            continue
        sentiment = verdict.get("brand_sentiment")
        raw_tags = verdict.get("brand_evaluation_tags")
        if sentiment not in _SENTIMENTS or not isinstance(raw_tags, list) or not raw_tags:
            continue
        clean_tags = list(dict.fromkeys(
            tag.strip() for tag in raw_tags
            if isinstance(tag, str) and tag.strip()
        ))
        if not clean_tags or len(clean_tags) > 5:
            continue
        sentiments[sentiment] += 1
        tags.update(clean_tags)
        quote = verdict.get("brand_evidence_quote")
        if isinstance(quote, str) and quote.strip():
            evidence_rows.append(
                f'<tr><td>{_e(_ENGINE_NAMES[engine])}</td><td>{_e(_SENTIMENTS[sentiment])}</td>'
                f'<td>{_e("、".join(clean_tags))}</td><td>{_e(quote.strip())}</td></tr>'
            )
    if not sentiments:
        return '<p class="empty">该达标批次没有可比较的品牌评价数据；缺失字段不按中性计算。</p>'
    chips = "".join(f'<span class="sentiment">{_e(_SENTIMENTS[key])} {count}</span>'
                    for key, count in sorted(sentiments.items()))
    tag_rows = "".join(f'<tr><td>{_e(tag)}</td><td>{count}</td></tr>'
                       for tag, count in tags.most_common())
    detail = ("<table><thead><tr><th>平台</th><th>倾向</th><th>评价标签</th><th>回答摘录</th></tr></thead><tbody>"
              + "".join(evidence_rows) + "</tbody></table>" if evidence_rows else "")
    return (f'<div class="sentiments">{chips}</div><h4>评价标签</h4>'
            f'<table><thead><tr><th>标签</th><th>出现次数</th></tr></thead><tbody>{tag_rows}</tbody></table>'
            f'<h4>平台评价证据</h4>{detail}')


def _event_platform_metrics(events: list[dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    output: dict[str, list[tuple[str, float]]] = {engine: [] for engine in _ENGINES}
    for event in events:
        label = _short_date(event["time"])
        for engine in _ENGINES:
            verdict = _verdict(event["item"]["rows"].get(engine, {})) if engine in event["item"]["rows"] else None
            if verdict is None or verdict.get("citation_status") not in {"cited", "not_cited"}:
                continue
            # The chart is scoped to question-batches that passed the report gate.
            total, cited = output.get(f"_count_{engine}", (0, 0))
            output[f"_count_{engine}"] = (total + 1, cited + int(verdict["citation_status"] == "cited"))
            output[engine].append((label, 0.0))
    # The compact chart uses one rate point per date over all qualified question batches.
    for engine in _ENGINES:
        total, cited = output.pop(f"_count_{engine}", (0, 0))
        if total:
            date_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for event in events:
                label = _short_date(event["time"])
                rows = event["item"]["rows"]
                row = rows.get(engine)
                verdict = _verdict(row) if row else None
                if verdict is not None and verdict.get("citation_status") in {"cited", "not_cited"}:
                    date_counts[label][0] += 1
                    date_counts[label][1] += int(verdict["citation_status"] == "cited")
            output[engine] = [(label, values[1] / values[0] * 100)
                              for label, values in sorted(date_counts.items())]
        else:
            output[engine] = []
    return output


def _coverage_section(records: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> str:
    lines = []
    for record, summary in zip(records, summaries):
        coverage = _coverage(record)
        if (summary["complete"] and summary["rate"] is not None
                and summary["unknown"] == 0 and coverage["verdicts"] == coverage["expected"]
                and coverage["citations_partial"] == 0 and coverage["citations_unknown"] == 0):
            continue
        if record.get("read_error"):
            reason = record["read_error"]
        elif not summary["complete"]:
            reason = "运行未完整结束" if not record["data"].get("run_error") else "运行已中断"
        elif summary["decided"] == 0:
            reason = "没有可确认结果，未进入趋势分母"
        elif summary["unknown"]:
            reason = "部分问题 AI 判定缺失或引用状态不确定，未进入对应问题的分母"
        elif coverage["citations_partial"] or coverage["citations_unknown"]:
            reason = "引用来源采集不完整或未报告完整度，来源排名只反映已采集内容"
        else:
            reason = "部分平台缺少明确 AI 判定，未计入相应问题的分母"
        link = _report_link(record["folder"])
        lines.append(
            f'<tr><td><a href="{_e(link)}">{_e(_format_date(record["time"]))}</a></td>'
            f'<td>{_e(record["brand"] or "品牌未知")}</td><td>{_e(reason)}</td>'
            f'<td>{coverage["answered"]}/{coverage["expected"]} 回答，'
            f'{coverage["verdicts"]}/{coverage["expected"]} 明确判定，'
            f'引用采集完整 {coverage["citations_complete"]}、不完整 {coverage["citations_partial"]}、'
            f'未报告 {coverage["citations_unknown"]}</td></tr>'
        )
    if not lines:
        return '<p class="empty">筛选范围内的记录均可用于当前趋势统计。</p>'
    return ('<table><thead><tr><th>检测时间</th><th>品牌</th><th>未计入原因</th><th>覆盖情况</th></tr></thead><tbody>'
            + "".join(lines) + "</tbody></table>")


def build_trend_html(
    reports_root: str | Path,
    *,
    brand: str | None = None,
    days: int | None = None,
    keyword: str | None = None,
    now: datetime | None = None,
) -> str:
    """Create a complete, escaped HTML trends report without network access."""
    if days is not None and days < 1:
        raise ValueError("days 必须是正整数")
    records = _read_records(reports_root)
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time - timedelta(days=days) if days is not None else None
    selected = []
    for record in records:
        if brand and _norm(record["brand"]) != _norm(brand):
            continue
        if cutoff and record["time"] and record["time"] < cutoff:
            continue
        if cutoff and record["time"] is None:
            continue
        selected.append(record)

    summaries = [_batch_summary(record, keyword) for record in selected]
    batch_points = [(summary["record"]["time"], summary["rate"], summary)
                    for summary in summaries if summary["rate"] is not None]
    batch_series = [("达标率", "#147d73", [(_short_date(time), rate)
                                            for time, rate, _ in batch_points])]
    platform_events: list[dict[str, Any]] = []
    series_groups: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for record in selected:
        if not record["articles"]:
            continue
        for item in _eligible_outcomes(record, keyword):
            if item["state"] != "qualified":
                continue
            key = (_norm(record["brand"]), item["key"], record["articles"])
            group = series_groups.setdefault(key, {
                "brand": record["brand"], "question": item["question"],
                "articles": record["articles"], "events": [],
            })
            event = _event_for(record, item)
            group["events"].append(event)
            platform_events.append(event)
    for group in series_groups.values():
        group["events"].sort(key=lambda event: (event["time"] or datetime.min.replace(tzinfo=timezone.utc),
                                                  event["record"]["folder"]))
    platform_rates = _event_platform_metrics(platform_events)
    colors = ("#147d73", "#386cb0", "#b35c32", "#7462a8", "#558248")
    platform_chart = _line_chart(
        "各平台目标文章引用率（仅达标问题）",
        [(_ENGINE_NAMES[engine], colors[index], platform_rates[engine])
         for index, engine in enumerate(_ENGINES)],
    )

    query_sections: list[str] = []
    for group in sorted(series_groups.values(), key=lambda item: (_norm(item["brand"]), item["question"])):
        events = group["events"]
        previous_signature: tuple[tuple[str, str], ...] | None = None
        event_sections = []
        for index, event in enumerate(events):
            record = event["record"]
            models = event["models"]
            if previous_signature is not None and models is not None and models != previous_signature:
                model_note = '<span class="flag">模型变化</span>'
            elif models is None:
                model_note = '<span class="muted">模型信息未记录</span>'
            else:
                model_note = '<span class="muted">模型：' + _e(", ".join(f"{_ENGINE_NAMES.get(engine, engine)} {model}" for engine, model in models)) + '</span>'
            if models is not None:
                previous_signature = models
            targets = group["articles"]
            current_article_rank, article_error = _rank_articles(event, targets)
            current_site_rank = _rank_sites(event)
            if index:
                previous = events[index - 1]
                previous_article_rank, previous_article_error = _rank_articles(previous, targets)
                previous_site_rank = _rank_sites(previous)
            else:
                previous_article_rank, previous_article_error, previous_site_rank = None, None, None
            article_html = _rank_table(
                "目标文章排名变化（最近两次达标记录）", previous_article_rank,
                current_article_rank, unavailable=article_error or previous_article_error,
            )
            site_html = _rank_table("来源网站排名变化（最近两次达标记录）",
                                    previous_site_rank, current_site_rank)
            if index < len(events) - 1:
                # Comparisons should be shown only on the newest event, not repeated in old rows.
                article_html = _rank_table("目标文章排名", None, current_article_rank,
                                           unavailable=article_error)
                site_html = _rank_table("来源网站排名", None, current_site_rank)
            link = _report_link(record["folder"])
            event_sections.append(
                f'<article class="event"><header><h3>{_e(_format_date(event["time"]))}</h3>'
                f'<a href="{_e(link)}">阅读本次记录</a>{model_note}</header>'
                f'<p class="coverage">问题已达标；{_e(_query_coverage_text(record, event["item"]))}。'
                f'{"本次检测完整。" if _execution_complete(record) else "本次检测未完整结束。"}</p>'
                f'{article_html}{site_html}<h4>品牌评价趋势</h4>{_assessment(event)}</article>'
            )
        # Newest two eligible batches carry direct rank movement comparisons.
        if len(events) >= 2:
            newest = events[-1]
            prior = events[-2]
            article_old, article_old_error = _rank_articles(prior, group["articles"])
            article_new, article_new_error = _rank_articles(newest, group["articles"])
            site_old, site_new = _rank_sites(prior), _rank_sites(newest)
            prior_link = _report_link(prior["record"]["folder"])
            newest_link = _report_link(newest["record"]["folder"])
            compare = (
                '<section class="comparison"><h3>最近两次达标记录对比</h3>'
                f'<p><a href="{_e(prior_link)}">{_e(_format_date(prior["time"]))}</a> → '
                f'<a href="{_e(newest_link)}">{_e(_format_date(newest["time"]))}</a></p>'
                + _rank_table("目标文章排名变化", article_old, article_new,
                              unavailable=article_new_error or article_old_error)
                + _rank_table("来源网站排名变化", site_old, site_new)
                + '</section>'
            )
            # Remove per-event duplicate tables from the newest two cards and put one comparison above.
            if event_sections:
                for i in range(max(0, len(event_sections) - 2), len(event_sections)):
                    event_sections[i] = re.sub(r'<h4>(?:目标文章排名变化（最近两次达标记录）|目标文章排名|来源网站排名变化（最近两次达标记录）|来源网站排名)</h4>.*?</table>', '', event_sections[i])
        else:
            compare = ""
        article_labels = "、".join(group["articles"])
        query_sections.append(
            f'<section class="query-series"><h2>{_e(group["brand"])} · {_e(group["question"])}</h2>'
            f'<p class="muted">目标文章集合：{_e(article_labels)}</p>{compare}'
            + "".join(event_sections) + '</section>'
        )

    if batch_points:
        batch_table_rows = []
        previous_model = None
        for _, rate, summary in batch_points:
            record = summary["record"]
            models = summary["models"]
            change = "模型变化" if previous_model is not None and models is not None and models != previous_model else "—"
            if models is not None:
                previous_model = models
            batch_table_rows.append(
                f'<tr><td><a href="{_e(_report_link(record["folder"]))}">{_e(_format_date(record["time"]))}</a></td>'
                f'<td>{summary["qualified"]}/{summary["decided"]}（{rate:.1f}%）</td>'
                f'<td>{_e(change)}</td><td>{_e(_query_coverage_text(record))}</td></tr>'
            )
        batch_table = ('<table><thead><tr><th>检测批次</th><th>达标问题 / 可判问题</th><th>模型</th><th>覆盖</th></tr></thead><tbody>'
                       + "".join(batch_table_rows) + "</tbody></table>")
    else:
        batch_table = '<p class="empty">没有完整且至少含一个可判问题的检测批次。</p>'
    batch_chart = _line_chart("完整检测批次达标率", batch_series)
    coverage_html = _coverage_section(selected, summaries)
    date_note = f"最近 {days} 天" if days else "全部时间"
    filters = []
    if brand:
        filters.append(f"品牌：{brand}")
    if keyword:
        filters.append(f"关键词：{keyword}")
    scope = "；".join(filters) if filters else "全部品牌与问题"
    if not selected:
        query_content = '<p class="empty">当前筛选没有历史记录。</p>'
    elif not query_sections:
        query_content = '<p class="empty">没有可展示的达标问题趋势。只有曾达到记录条件的问题会展示逐题平台、排名和评价数据。</p>'
    else:
        query_content = "".join(query_sections)
    html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO 历史趋势记录</title><style>
:root{{--ink:#182b2b;--muted:#5f7272;--line:#d9e2e0;--paper:#fff;--wash:#f3f7f6;--teal:#147d73;--coral:#b35c32}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--wash);color:var(--ink);font:15px/1.55 "Segoe UI","Microsoft YaHei",sans-serif}}
main{{max-width:1120px;margin:0 auto;padding:32px 24px 56px}}h1{{font-size:27px;margin:0 0 6px}}h2{{font-size:21px;margin:0 0 8px}}h3{{font-size:17px;margin:0}}h4{{font-size:15px;margin:20px 0 8px}}
.subtitle,.muted{{color:var(--muted)}}.section{{padding:24px 0;border-top:1px solid var(--line)}}.query-series{{padding:24px 0;border-top:2px solid #bdceca}}
.event,.comparison{{padding:18px 0;border-top:1px solid var(--line)}}.comparison{{border:1px solid var(--line);padding:16px;margin:16px 0;background:white}}
.event header{{display:flex;align-items:center;gap:16px;flex-wrap:wrap}}a{{color:#176b65}}a:hover{{text-decoration-thickness:2px}}table{{width:100%;border-collapse:collapse;margin:8px 0 18px;background:var(--paper);font-size:14px}}
th,td{{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left;vertical-align:top}}th{{background:#e9f0ee;font-weight:600}}.empty{{color:var(--muted);padding:8px 0}}
.trend-chart{{display:block;width:100%;max-width:800px;height:auto;background:white;border:1px solid var(--line)}}.grid{{stroke:#e0e8e6;stroke-width:1}}.axis{{fill:#536765;font-size:11px}}.chart-title{{fill:#182b2b;font-size:13px;font-weight:600}}
.legend,.sentiments{{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 12px}}.legend span{{display:inline-flex;align-items:center;gap:6px}}.legend i{{width:12px;height:4px;display:inline-block}}.sentiment,.flag{{display:inline-block;padding:2px 8px;border-radius:3px;background:#e4efed;color:#175e57}}.flag{{background:#fff0e7;color:#8a472b}}
.coverage{{color:var(--muted);font-size:13px}}@media(max-width:680px){{main{{padding:22px 14px}}table{{font-size:12px}}th,td{{padding:7px 6px}}}}
</style></head><body><main>
<h1>GEO 历史趋势记录</h1><p class="subtitle">{_e(scope)} · {_e(date_note)} · {len(selected)} 个检测批次</p>
<section class="section"><h2>整体达标率</h2><p class="muted">仅统计完整结束的检测批次；每个问题只在至少一平台明确提及品牌且 AI 确认引用目标文章时计为达标。缺少判定的问题不进入分母。</p>{batch_chart}{batch_table}</section>
<section class="section"><h2>各平台目标文章引用趋势</h2><p class="muted">只统计曾达到记录条件的问题；只对平台 AI 明确判定“已引用”或“未引用”的结果计算比例。</p>{platform_chart}</section>
<section class="section"><h2>达标关键词记录</h2>{query_content}</section>
<section class="section"><h2>未纳入趋势的记录</h2><p class="muted">不完整检测和缺少明确 AI 判定的数据不会作为零值处理。</p>{coverage_html}</section>
</main></body></html>'''
    return html

