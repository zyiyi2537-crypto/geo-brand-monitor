"""Show whether the operator's articles appeared in the captured AI citations."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from .brand_mentions import summarize_mentions

_ENGINE_NAMES = {
    "deepseek": "DeepSeek",
    "doubao": "豆包",
    "yuanbao": "元宝",
    "wenxin": "文心一言",
    "qwen": "千问",
}
_BEIJING_TIME = timezone(timedelta(hours=8))
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~])")
_URL_SAFE = ":/?#[]@!$&'()*+,;=%-._~"


def _plain(value: object) -> str:
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _markdown(value: object) -> str:
    """Keep untrusted answer and question text inert in Markdown."""
    safe = html.escape(_plain(value), quote=False)
    return _MARKDOWN_SPECIAL.sub(r"\\\1", safe)


def _safe_http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        if parts.username or parts.password:
            return None
    except ValueError:
        return None
    return url


def _named_link(label: str, url: str) -> str:
    return f"[{_markdown(label)}]({quote(url, safe=_URL_SAFE.replace('(', '').replace(')', ''))})"


def _percentage(numerator: int, denominator: int) -> int | None:
    return round(numerator * 100 / denominator) if denominator else None


_METRIC_PATTERN = re.compile(r"^(\d+)/(\d+)[（(](\d+(?:\.\d+)?)%[）)]$")


def _metric(value: str) -> tuple[int, int, int | float] | None:
    match = _METRIC_PATTERN.fullmatch(value)
    if not match:
        return None
    count, total = (int(part) for part in match.groups()[:2])
    if total <= 0 or count > total:
        return None
    rate = round(count * 100 / total, 2) if '.' in match.group(3) else (_percentage(count, total) or 0)
    return count, total, rate


def _qualification_chart(value: str) -> str:
    metric = _metric(value)
    if not metric:
        return ""
    count, total, rate = metric
    return (
        '<section class="report-chart" aria-label="本次问题达标比例">'
        '<h2>本次达标情况</h2>'
        f'<div class="qualification-chart"><div><strong>{count}/{total}</strong>'
        f'<span>个问题达到记录条件</span></div><div class="qualification-track" '
        f'role="meter" aria-label="问题达标率：{count}/{total}，{rate}%" '
        f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{rate}">'
        f'<span style="width:{rate}%"></span></div><p>达标率 {rate}%</p></div></section>'
    )


def _platform_chart(data_rows: list[list[str]]) -> str:
    rows: list[str] = []
    for item in data_rows:
        if len(item) != 3 or item[0] not in _ENGINE_NAMES.values():
            continue
        cells = []
        for value, label, color in ((item[1], "品牌提及", "brand"),
                                    (item[2], "目标文章引用", "citation")):
            metric = _metric(value)
            if metric is None:
                continue
            count, denominator, percent = metric
            value_label = f"{count}/{denominator}（{percent}%）"
            cells.append(
                f'<div class="chart-measure {color}"><div class="measure-heading">'
                f'<span>{label}</span><span>{value_label}</span></div>'
                f'<div class="measure-track" role="meter" aria-label="{label}：{value_label}" '
                f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent}">'
                f'<span style="width:{percent}%"></span></div></div>'
            )
        if cells:
            rows.append(
                '<div class="chart-row"><div class="chart-engine">'
                f'{html.escape(item[0], quote=False)}</div>'
                f'<div class="chart-metrics">{"".join(cells)}</div></div>'
            )
    if not rows:
        return ""
    return (
        '<div class="platform-chart" aria-label="全部问题的平台百分比">'
        '<p class="chart-note">品牌提及率与目标文章引用率分别按已完成的对应判定计算。</p>'
        '<div class="chart-legend"><span class="legend-brand">品牌提及</span>'
        '<span class="legend-citation">目标文章引用</span></div>'
        + "".join(rows) + '</div>'
    )


def _inline_html(value: str) -> str:
    """Render the small safe inline-Markdown subset used by this report."""
    token = re.compile(r"<https?://[^>\s]+>|\[(?:\\.|[^\]\\])*\]\((?:https?://[^\s)]+|#[A-Za-z0-9_-]+)\)|\*\*.*?\*\*|\\[\\`*_{}\[\]()#+\-.!|~]")
    pieces: list[str] = []
    position = 0
    for match in token.finditer(value):
        pieces.append(html.escape(html.unescape(value[position:match.start()]), quote=False))
        item = match.group(0)
        if item.startswith("<"):
            url = _safe_http_url(item[1:-1])
            if url:
                escaped = html.escape(url, quote=True)
                pieces.append(f'<a href="{escaped}">{html.escape(url, quote=False)}</a>')
            else:
                pieces.append(html.escape(html.unescape(item), quote=False))
        elif item.startswith("["):
            label, url = item[1:-1].rsplit("](", 1)
            url = url if re.fullmatch(r"#[A-Za-z0-9_-]+", url) else _safe_http_url(url)
            if url:
                pieces.append(f'<a href="{html.escape(url, quote=True)}">{_inline_html(label)}</a>')
            else:
                pieces.append(html.escape(item, quote=False))
        elif item.startswith("**"):
            pieces.append(f"<strong>{_inline_html(item[2:-2])}</strong>")
        else:
            pieces.append(html.escape(html.unescape(item[1:]), quote=False))
        position = match.end()
    pieces.append(html.escape(html.unescape(value[position:]), quote=False))
    return "".join(pieces)


def render_html(markdown: str, *, config: dict | None = None,
                results: list[dict] | None = None,
                report_directory: str | Path | None = None) -> str:
    """Render the report as a self-contained, readable HTML document."""
    blocks: list[str] = []
    paragraph: list[str] = []
    table: list[list[str]] = []
    audit = audit_matrix = ""
    if config is not None and results is not None:
        markdown = markdown.partition("\n## 浏览器证据与全部引用来源\n")[0]
        audit_matrix, audit = _audit_html(config, results, report_directory)
        before, separator, after = markdown.partition("\n## 全部问题核查明细\n")
        if separator:
            _, ranking_heading, ranking_text = after.partition("\n## 问题引用排名与品牌评价\n")
            markdown = before + separator + ranking_heading + ranking_text
    ranking_section = False
    brand_section = False
    ranking_open = False
    brand_item_open = False
    code_lines: list[str] | None = None
    code_fence = ""

    def flush_paragraph() -> None:
        if paragraph:
            contents = "<br>\n".join(_inline_html(line) for line in paragraph)
            blocks.append(f"<p>{contents}</p>")
            paragraph.clear()

    def flush_table() -> None:
        if not table:
            return
        headers, *rows = table
        head = "".join(f'<th scope="col">{_inline_html(cell)}</th>' for cell in headers)
        body = []
        for row in rows:
            cells = []
            for column, value in enumerate(row):
                state = ("yes" if value.startswith(("已引用", "已提及"))
                         else "no" if value in ("未引用", "未提及")
                         else "pending" if value == "待核对" else "")
                content = _inline_html(value)
                metric = _metric(value) if headers and headers[0] == "排名" else None
                if metric:
                    count, total, rate = metric
                    label = html.escape(headers[column] if column < len(headers) else "覆盖率", quote=True)
                    content = (f'<span class="rank-rate">{content}</span>'
                               f'<span class="rank-track" role="meter" aria-label="{label}：{count}/{total}，{rate}%" '
                               f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{rate}">'
                               f'<span style="width:{rate}%"></span></span>')
                if state:
                    content = f'<span class="status {state}">{content}</span>'
                cells.append(f"<td>{content}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        table_class = ' ranking-table' if headers and headers[0] == "排名" else ''
        table_class += ' brand-ranking-table' if brand_section else ''
        region = ' tabindex="0" role="region" aria-label="其他品牌完整排名，可滚动查看"' if brand_section else ''
        blocks.append(f'<div class="table-wrap{table_class}"{region}><table><thead><tr>' + head
                      + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>')
        if headers == ["指标", "结果"]:
            for row in rows:
                if len(row) == 2 and row[0] == "达到记录条件的问题":
                    chart = _qualification_chart(row[1])
                    if chart:
                        blocks.append(chart)
        elif headers == ["平台", "品牌提及", "目标文章引用"]:
            chart = _platform_chart(rows)
            if chart:
                blocks.append(chart)
        table.clear()

    for line in markdown.splitlines():
        if (code_lines is None and re.fullmatch(r"`{3,}", line)) or (code_lines is not None and line == code_fence):
            if code_lines is None:
                flush_paragraph()
                flush_table()
                code_fence = line
                code_lines = []
            else:
                blocks.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
                code_lines = None
            continue
        if code_lines is not None:
            code_lines.append(line)
            continue
        if line.startswith("| ") and line.endswith(" |"):
            flush_paragraph()
            cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line[1:-1])]
            if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                table.append(cells)
            continue
        flush_table()
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            if level <= 4 and brand_item_open:
                blocks.append("</div></details>")
                brand_item_open = False
            if level <= 3 and ranking_open:
                blocks.append("</div></details>")
                ranking_open = False
            if level <= 2:
                ranking_section = heading.group(2) == "问题引用排名与品牌评价"
                brand_section = heading.group(2) == "其他品牌提及排名"
            if (ranking_section or brand_section) and level == 3:
                detail_class = "ranking" if ranking_section else "brand-all-evidence"
                blocks.append(f'<details class="{detail_class}"><summary>'
                              + _inline_html(heading.group(2)) + '</summary><div class="detail-body">')
                ranking_open = True
                continue
            if brand_section and level == 4:
                rank = re.match(r"第 (\d+) 名", heading.group(2))
                anchor = f' id="brand-{rank.group(1)}"' if rank else ''
                blocks.append('<details class="brand-evidence"><summary>'
                              + _inline_html(heading.group(2)) + f'</summary><div class="detail-body"{anchor}>')
                brand_item_open = True
                continue
            anchor = ' id="brand-mentions"' if heading.group(2) == "其他品牌提及排名" else ''
            blocks.append(f"<h{level}{anchor}>{_inline_html(heading.group(2))}</h{level}>")
            if heading.group(2) == "全部问题核查明细" and audit_matrix:
                blocks.append(audit_matrix)
        elif line.strip():
            paragraph.append(line)
        else:
            flush_paragraph()
    flush_paragraph()
    flush_table()
    if code_lines is not None:
        blocks.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
    if brand_item_open:
        blocks.append("</div></details>")
    if ranking_open:
        blocks.append("</div></details>")

    body = "\n".join(blocks) + audit
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>GEO 引用监测记录</title><style>"
        "*{box-sizing:border-box}body{max-width:1100px;margin:40px auto;padding:0 24px;"
        "font:15px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;"
        "color:#202631;background:#fff}h1{font-size:30px;margin-bottom:12px}"
        "h2{font-size:21px;margin:36px 0 8px;padding-bottom:8px;border-bottom:1px solid #e7eaf0}"
        "p{margin:12px 0}a{color:#1769aa;overflow-wrap:anywhere}strong{color:#182230}"
        ".table-wrap{overflow-x:auto;margin:16px 0;border:1px solid #e3e8ef;border-radius:8px}"
        "table{width:100%;border-collapse:collapse}th,td{padding:12px 14px;text-align:left;"
        "vertical-align:top;border-bottom:1px solid #e7eaf0}th{background:#f4f6f9;white-space:nowrap}"
        "tbody tr:last-child td{border-bottom:0}td:not(:first-child){min-width:95px}"
        "td:first-child{min-width:210px}tbody tr:nth-child(even){background:#fafbfd}"
        ".status{font-weight:600}.yes{color:#087443}.no{color:#4b5563}.pending{color:#99600c}"
        ".report-chart{margin:32px 0 40px;padding:0 0 24px;border-bottom:1px solid #e3e8ef}"
        ".report-chart h2{margin-top:0}.report-chart h3{font-size:17px;margin:28px 0 4px}"
        ".qualification-chart{max-width:640px;padding:4px 0 16px}"
        ".qualification-chart>div:first-child{display:flex;align-items:baseline;gap:10px}"
        ".qualification-chart strong{font-size:26px;color:#176d68}.qualification-chart p{margin:6px 0}"
        ".qualification-track,.measure-track{height:9px;background:#edf1f2;border-radius:5px;overflow:hidden}"
        ".qualification-track{margin-top:10px}.qualification-track span,.measure-track span{"
        "display:block;height:100%;border-radius:inherit;background:#176d68}"
        ".chart-note{font-size:13px;color:#56616b;margin:4px 0 12px}.platform-chart{margin:8px 0 24px}"
        ".chart-legend{display:flex;gap:18px;font-size:13px;margin:8px 0 4px}"
        ".legend-brand:before,.legend-citation:before{content:'';display:inline-block;width:9px;height:9px;"
        "border-radius:50%;margin-right:6px}.legend-brand:before{background:#2f6f9f}"
        ".legend-citation:before{background:#198754}.chart-row{display:grid;grid-template-columns:145px 1fr;"
        "gap:16px;padding:12px 0;border-bottom:1px solid #eef0f2}.chart-engine{font-weight:600;padding-top:4px}"
        ".chart-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}"
        ".measure-heading{display:flex;justify-content:space-between;gap:8px;font-size:13px;margin-bottom:6px}"
        ".measure-heading span:last-child{font-variant-numeric:tabular-nums;color:#34404a}"
        ".brand .measure-track span{background:#2f6f9f}.citation .measure-track span{background:#198754}"
        "details.ranking,details.platform,details.brand-evidence,details.brand-all-evidence{margin:12px 0;border:1px solid #e3e8ef;border-radius:10px;overflow:hidden}"
        "summary{cursor:pointer;padding:15px 18px;background:#f7f9fc;font-weight:600}"
        "details[open]>summary{border-bottom:1px solid #e3e8ef}.detail-body{padding:8px 18px 18px;min-width:0}"
        "details.sub{margin:12px 0}details.sub>summary{padding:10px 12px;border-radius:6px;background:#f5f7fa}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:14px;line-height:1.85;"
        "background:#f8fafc;padding:16px;border-radius:8px}"
        ".ranking-table td:first-child{min-width:50px}.ranking-table td:nth-child(2){min-width:250px}"
        ".brand-ranking-table{max-height:550px;overflow:auto}.brand-ranking-table th{position:sticky;top:0;z-index:1}"
        ".brand-ranking-table td:nth-child(2){min-width:160px}.brand-evidence{scroll-margin-top:16px}"
        ".rank-rate{white-space:nowrap;font-variant-numeric:tabular-nums}.rank-track{display:block;"
        "height:7px;min-width:110px;margin-top:7px;border-radius:4px;background:#e8edf5;overflow:hidden}"
        ".rank-track>span{display:block;height:100%;background:#4478cf;border-radius:inherit}"
        ".sources{padding-left:28px}.sources li{padding:10px 4px;border-bottom:1px solid #edf0f4}"
        ".sources small,.muted{display:block;color:#657182;font-size:13px;overflow-wrap:anywhere}"
        ".evidence-links{display:flex;gap:16px;flex-wrap:wrap}.audit-matrix td{min-width:110px!important}"
        ".audit-matrix td small{margin-top:5px}.audit-matrix th:first-child{white-space:normal;min-width:260px}"
        ".audit-question{scroll-margin-top:18px}.audit-question h3{margin:28px 0 12px}"
        ".platform:has(:target){border-color:#1769aa;box-shadow:0 0 0 2px #dceeff}.detail-body:target{scroll-margin-top:70px}"
        ".citation-target{background:#edf9f3}"
        "@media(max-width:600px){body{margin:24px auto;padding:0 16px}h1{font-size:25px}}"
        "@media(max-width:600px){.chart-row{grid-template-columns:1fr;gap:4px}.chart-metrics{grid-template-columns:1fr;gap:12px}}"
        "@media print{body{margin:0;max-width:none;padding:0;font-size:11px}.table-wrap{overflow:visible}"
        ".brand-ranking-table{max-height:none}.brand-ranking-table th{position:static}"
        "th,td{padding:7px;min-width:0!important}tr{break-inside:avoid}a{color:inherit}"
        ".report-chart{break-inside:avoid}}"
        f"</style></head><body>{body}</body></html>\n"
    )


def _article_index(articles: object) -> dict[str, tuple[str, str]]:
    index: dict[str, tuple[str, str]] = {}
    if not isinstance(articles, list):
        return index
    for item in articles:
        if not isinstance(item, dict):
            continue
        url = _safe_http_url(item.get("url"))
        if not url:
            continue
        index.setdefault(url, (_plain(item.get("title")) or "已发布文章", url))
    return index


def _time_label(generated_at: datetime | None) -> str:
    moment = generated_at or datetime.now(_BEIJING_TIME)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_BEIJING_TIME)
    else:
        moment = moment.astimezone(_BEIJING_TIME)
    return moment.strftime("%Y年%m月%d日 %H:%M（北京时间）")


def _declared_reference_count(answer: str) -> int | None:
    match = re.search(r"(?:参考\s*(\d+)\s*(?:篇|个|条)\s*(?:资料|来源|网页)|搜索到\s*(\d+)\s*个网页|搜索全网\s*(\d+)\s*篇资料)", answer[:500])
    return int(next(group for group in match.groups() if group is not None)) if match else None


def _source_site(url: str) -> str | None:
    """Return a stable host label for grouping already-collected source URLs."""
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _observations(questions: list[str], grouped: dict, articles: dict) -> dict:
    observations: dict[str, dict[str, dict]] = {}
    for question in questions:
        observations[question] = {}
        for engine in _ENGINE_NAMES:
            rows = grouped[question][engine]
            successful = [
                row for row in rows
                if not row.get("error") and isinstance(row.get("answer"), str)
                and row["answer"].strip()
            ]
            if not successful:
                observations[question][engine] = {
                    "matches": [], "sources": [], "citation": "uncertain",
                    "brand": None, "matched_citations": [], "assessment": None,
                }
                continue
            row = successful[0]
            verdict = row.get("ai_verdict")
            if not isinstance(verdict, dict):
                verdict = {}
            brand_mentioned = verdict.get("brand_mentioned")
            if not isinstance(brand_mentioned, bool):
                brand_mentioned = None
            citation_status = verdict.get("citation_status")
            if citation_status not in ("cited", "not_cited", "uncertain"):
                citation_status = "uncertain"
            targets = verdict.get("matched_article_urls")
            sources = verdict.get("evidence_urls")
            targets = targets if isinstance(targets, list) else []
            sources = sources if isinstance(sources, list) else []
            citations = row.get("citations")
            citations = citations if isinstance(citations, list) else []
            captured = {
                url for citation in citations if isinstance(citation, dict)
                for url in [_safe_http_url(citation.get("url"))] if url
            }
            declared = _declared_reference_count(row["answer"])
            collection = row.get("citation_collection")
            collection = collection if isinstance(collection, dict) else {}
            if isinstance(collection.get("expected_count"), int):
                declared = collection["expected_count"]
            incomplete_sources = (collection.get("complete") is False
                                  or declared is not None and len(citations) != declared)
            confirmed_empty = collection.get("complete") is True and declared == 0 and not citations
            matches = list(dict.fromkeys(url for url in targets if isinstance(url, str) and url in articles))
            evidence = list(dict.fromkeys(url for url in sources if isinstance(url, str) and url in captured))
            if (row.get("ai_error") or (citation_status == "cited" and (
                    not matches or not evidence
                    or not all(isinstance(url, str) and url in articles for url in targets)
                    or not all(isinstance(url, str) and url in captured for url in sources)))
                    or (citation_status == "not_cited" and ((not captured and not confirmed_empty) or targets or sources or incomplete_sources))):
                citation_status = "uncertain"
            matched_citations: list[tuple[str, str]] = []
            pairs = verdict.get("matched_citations")
            if citation_status == "cited" and isinstance(pairs, list):
                for pair in pairs:
                    if not isinstance(pair, dict):
                        continue
                    article_url = pair.get("article_url")
                    citation_url = pair.get("citation_url")
                    if (article_url in matches and citation_url in evidence
                            and (article_url, citation_url) not in matched_citations):
                        matched_citations.append((article_url, citation_url))
            sentiment = verdict.get("brand_sentiment") if brand_mentioned is True else None
            if sentiment not in {"positive", "neutral", "negative", "mixed"}:
                sentiment = None
            raw_tags = verdict.get("brand_evaluation_tags") if brand_mentioned is True else []
            tags = list(dict.fromkeys(
                _plain(tag)[:40] for tag in raw_tags
                if isinstance(tag, str) and _plain(tag)
            ))[:5] if isinstance(raw_tags, list) else []
            quote = verdict.get("brand_evidence_quote") if brand_mentioned is True else None
            assessment = {
                "sentiment": sentiment,
                "tags": tags,
                "quote": _plain(quote)[:180] if isinstance(quote, str) else "",
            } if brand_mentioned is True else None
            observations[question][engine] = {
                "matches": matches if citation_status == "cited" else [],
                "sources": evidence if citation_status == "cited" else [],
                "citation": citation_status,
                "brand": brand_mentioned,
                "matched_citations": matched_citations,
                "assessment": assessment,
            }

    return observations


def _evidence_url(value: object, directory: str | Path | None) -> str | None:
    """Link only to saved, readable image/text evidence."""
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        if directory is None:
            return None
        path = Path(directory) / path
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".txt"}:
        return None
    try:
        return path.resolve().as_uri() if path.is_file() else None
    except (OSError, ValueError):
        return None


def _audit_html(config: dict, results: list[dict], directory: str | Path | None) -> tuple[str, str]:
    questions = list(dict.fromkeys(_plain(q) for q in config.get("questions", []) if _plain(q)))
    grouped = {q: {engine: [] for engine in _ENGINE_NAMES} for q in questions}
    for row in results:
        if not isinstance(row, dict):
            continue
        query, engine = _plain(row.get("query")), row.get("engine")
        if query in grouped and engine in _ENGINE_NAMES:
            grouped[query][engine].append(row)
    observations = _observations(questions, grouped, _article_index(config.get("articles")))
    labels = {"cited": "已引用", "not_cited": "未引用", "uncertain": "待核对"}

    def link(label: str, url: str) -> str:
        return (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{html.escape(label)}</a>')

    matrix, details = [], []
    for number, question in enumerate(questions, 1):
        matrix_cells = [f'<th scope="row">{number:02d} · {html.escape(question)}</th>']
        platform_blocks = []
        for engine, name in _ENGINE_NAMES.items():
            rows = grouped[question][engine]
            row = next((r for r in rows if not r.get("error") and _plain(r.get("answer"))),
                       rows[0] if rows else {})
            observation = observations[question][engine]
            status = labels[observation["citation"]]
            if row.get("error"):
                status = "检查失败"
            elif not rows:
                status = "未执行"
            brand = ("已提及" if observation["brand"] is True else
                     "未提及" if observation["brand"] is False else "待核对")
            citations = row.get("citations")
            citations = citations if isinstance(citations, list) else []
            anchor = f'q{number}-{engine}'
            matrix_cells.append(
                f'<td><a href="#{anchor}">{status}</a>'
                f'<small class="muted">品牌{brand} · {len(citations)} 条来源</small></td>')
            evidence = []
            conversation = _safe_http_url(row.get("source_url"))
            if conversation:
                evidence.append(link("打开实际会话", conversation))
            for key, label in (("screenshot", "查看浏览器截图"), ("page_evidence", "查看页面文字")):
                url = _evidence_url(row.get(key), directory)
                if url:
                    evidence.append(link(label, url))
            content = ['<p class="evidence-links">' + "".join(evidence) + '</p>'] if evidence else []
            verdict = row.get("ai_verdict")
            verdict = verdict if isinstance(verdict, dict) else {}
            reason = _plain(verdict.get("reason"))
            if reason:
                content.append('<p><b>核查依据：</b>' + html.escape(reason) + '</p>')
            for key, label in (("error", "平台检查"), ("ai_error", "引用核对")):
                if _plain(row.get(key)):
                    content.append(f'<p><b>{label}：</b>{html.escape(_plain(row[key]))}</p>')
            collection = row.get("citation_collection")
            if isinstance(collection, dict):
                completeness = ("完整" if collection.get("complete") is True else
                                "不完整" if collection.get("complete") is False else "未报告完整度")
                expected = collection.get("expected_count")
                count_label = f" / 平台声明 {expected} 条" if isinstance(expected, int) else ""
                content.append(f'<p class="muted">来源采集：{completeness} · 已采集 {len(citations)} 条{count_label}</p>')
            answer = row.get("answer") if isinstance(row.get("answer"), str) else ""
            content.append('<details class="sub"><summary>完整回答</summary><pre>'
                           + html.escape(answer or "尚未取得回答") + '</pre></details>')
            source_items = []
            matched = set(observation["sources"])
            for index, citation in enumerate(citations, 1):
                if not isinstance(citation, dict):
                    continue
                url = _safe_http_url(citation.get("url"))
                title = _plain(citation.get("title")) or (url or "来源链接不可用")
                title_html = link(title, url) if url else html.escape(title)
                meta = _plain(citation.get("source_type")) or _plain(citation.get("domain"))
                position = citation.get("position")
                if isinstance(position, int):
                    meta += f" · 平台来源序号 {position}"
                if url in matched:
                    meta += " · AI 确认引用目标文章"
                snippet = _plain(citation.get("snippet"))
                source_items.append('<li' + (' class="citation-target"' if url in matched else '') + '>'
                                    + title_html + '<small>' + html.escape(meta) + '</small>'
                                    + ('<small>' + link(url, url) + '</small>' if url else '')
                                    + ('<p>' + html.escape(snippet) + '</p>' if snippet else '') + '</li>')
            content.append(f'<details class="sub"><summary>全部引用来源（{len(citations)} 条）</summary>'
                           + ('<ol class="sources">' + ''.join(source_items) + '</ol>'
                              if source_items else '<p>本次未采集到来源链接。</p>') + '</details>')
            platform_blocks.append(f'<details class="platform"><summary>{name} · '
                                   f'品牌{brand} · {status} · {len(citations)} 条来源</summary>'
                                   f'<div class="detail-body" id="{anchor}">' + ''.join(content) + '</div></details>')
        matrix.append('<tr>' + ''.join(matrix_cells) + '</tr>')
        details.append(f'<section class="audit-question"><h3>{number}. {html.escape(question)}</h3>'
                       + ''.join(platform_blocks) + '</section>')
    return ('<p class="muted">点击表格中的结果，查看完整回答、实际会话、已保存的截图和全部引用来源。</p>'
            '<div class="table-wrap audit-matrix"><table><thead><tr><th scope="col">问题</th>'
            + ''.join(f'<th scope="col">{name}</th>' for name in _ENGINE_NAMES.values())
            + '</tr></thead><tbody>' + ''.join(matrix) + '</tbody></table></div>',
            '<section id="browser-audit"><h2>浏览器证据与全部引用来源</h2>'
            + ''.join(details) + '</section>')


def _audit_markdown(questions: list[str], grouped: dict) -> list[str]:
    lines = ["", "## 浏览器证据与全部引用来源", ""]
    for number, question in enumerate(questions, 1):
        lines.extend([f"### 问题 {number}：{_markdown(question)}", ""])
        for engine, name in _ENGINE_NAMES.items():
            rows = grouped[question][engine]
            row = next((r for r in rows if not r.get("error") and _plain(r.get("answer"))),
                       rows[0] if rows else {})
            lines.extend([f"#### {name}", ""])
            url = _safe_http_url(row.get("source_url"))
            if url:
                lines.extend([_named_link("打开实际会话", url), ""])
            verdict = row.get("ai_verdict")
            if isinstance(verdict, dict) and _plain(verdict.get("reason")):
                lines.extend(["核查依据：" + _markdown(verdict["reason"]), ""])
            answer = row.get("answer") if isinstance(row.get("answer"), str) else ""
            fence = "`" * max(3, 1 + max((len(m.group()) for m in re.finditer(r"`+", answer)), default=0))
            lines.extend(["完整回答：", "", fence, answer or "尚未取得回答", fence, ""])
            citations = row.get("citations")
            citations = citations if isinstance(citations, list) else []
            lines.extend([f"全部引用来源（{len(citations)} 条）：", ""])
            for index, citation in enumerate(citations, 1):
                if not isinstance(citation, dict):
                    continue
                url = _safe_http_url(citation.get("url"))
                if url:
                    lines.extend([f"来源 {index}：" + _named_link(_plain(citation.get("title")) or url, url), ""])
    return lines


def _brand_ranking_lines(config: dict, results: list[dict]) -> list[str]:
    def rate(count: int, total: int) -> str:
        return f'{count * 100 / total:.2f}'.rstrip('0').rstrip('.')

    summary = summarize_mentions(config, results)
    analyzed, answered = summary["analyzed"], summary["answered"]
    lines = ["", "## 其他品牌提及排名", "",
             f"品牌分析覆盖：{analyzed}/{answered} 条已取得的有效回答。",
             "",
             "按提及该品牌的回答数排序；同一问题、同一平台重复提及只计一次，中英文名称及简称合并。"
             "只分析回答正文中的企业和厂商品牌，不把仅出现在引用来源中的名称计入。"
             "提及不代表推荐或产品质量评价。", ""]
    if analyzed < answered:
        lines.extend([f"另有 {answered - analyzed} 条回答的品牌分析尚未完成，以下比例仅以已分析回答为分母。", ""])
    if not analyzed:
        lines.extend(["尚无已完成的品牌分析，暂不能生成其他品牌排名。", ""])
        return lines
    lines.extend([f"目标品牌 {_markdown(config.get('brand'))} 的提及率见上方平台表现；本表统计其他品牌。", ""])
    if not summary["brands"]:
        lines.extend(["已分析的回答中未发现其他企业或厂商品牌。", ""])
        return lines
    lines.extend([f"共识别到 {len(summary['brands'])} 个其他品牌。表格可滚动查看完整排名，点击品牌名查看原文依据。", "",
                  "问题覆盖按至少一个平台提及该品牌的问题数计算；各平台列为提及回答数 / 已分析回答数。", "",
                  "| 排名 | 其他品牌 | 提及回答数 / 提及率 | 问题覆盖 | "
                  + " | ".join(_ENGINE_NAMES.values()) + " |",
                  "| ---: | --- | --- | --- | " + " | ".join("---" for _ in _ENGINE_NAMES) + " |"])
    for rank, item in enumerate(summary["brands"], 1):
        counts = " | ".join(f"{item['platforms'][e]}/{summary['platform_totals'][e]}"
                            if summary["platform_totals"][e] else "待分析" for e in _ENGINE_NAMES)
        lines.append(f"| {rank} | [{_markdown(item['name'])}](#brand-{rank}) | {item['count']}/{analyzed}"
                     f"（{rate(item['count'], analyzed)}%） | "
                     f"{item['questions']}/{summary['question_total']}"
                     f"（{rate(item['questions'], summary['question_total'])}%） | {counts} |")
    lines.extend(["", "展开下方品牌可查看实际出现的名称、原文摘录，并跳转到完整回答。", ""])
    lines.extend([f"### 全部品牌原文依据（{len(summary['brands'])} 个品牌）", ""])
    for rank, item in enumerate(summary["brands"], 1):
        lines.extend([f"#### 第 {rank} 名 · {_markdown(item['name'])} · {item['count']} 条回答", "",
                      "回答中出现的名称：" + "、".join(_markdown(a) for a in item["aliases"]), ""])
        for evidence in item["evidence"]:
            number, engine = evidence["question"], evidence["engine"]
            lines.extend([f"[问题 {number} · {_ENGINE_NAMES[engine]}](#q{number}-{engine})："
                          + _markdown(evidence["quote"]), ""])
    return lines


def build_report(
    config: dict,
    results: list[dict],
    generated_at: datetime | None = None,
    *,
    completed_questions: int | None = None,
) -> str:
    """Summarize confirmed results and retain every question and its evidence."""
    brand = _plain(config.get("brand"))
    if not brand:
        raise ValueError("报告配置缺少 brand")
    articles = _article_index(config.get("articles"))
    configured_questions = config.get("questions")
    questions: list[str] = []
    if isinstance(configured_questions, list):
        for value in configured_questions:
            question = _plain(value)
            if question and question not in questions:
                questions.append(question)

    grouped: dict[str, dict[str, list[dict]]] = {
        question: {engine: [] for engine in _ENGINE_NAMES} for question in questions
    }
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            query = _plain(result.get("query"))
            engine = result.get("engine")
            if query in grouped and isinstance(engine, str) and engine in _ENGINE_NAMES:
                grouped[query][engine].append(result)

    observations = _observations(questions, grouped, articles)

    all_checks = [item for current in observations.values() for item in current.values()]
    known_count = sum(item["citation"] != "uncertain" for item in all_checks)
    unknown_count = len(all_checks) - known_count
    qualified_questions = [
        question for question in questions
        if any(item["brand"] is True and item["citation"] == "cited"
               for item in observations[question].values())
    ]
    article_numbers = {url: number for number, url in enumerate(articles, 1)}
    total_questions = len(questions)
    inferred_finished_questions = sum(
        all(grouped[question][engine] for engine in _ENGINE_NAMES)
        for question in questions
    )
    question_rate = _percentage(len(qualified_questions), total_questions)
    finished_question_count = (
        inferred_finished_questions if completed_questions is None
        else max(0, min(completed_questions, total_questions))
    )
    all_questions_finished = finished_question_count >= total_questions
    has_successful_answer = any(
        not row.get("error") and isinstance(row.get("answer"), str) and row["answer"].strip()
        for row in results if isinstance(row, dict)
    )
    if qualified_questions:
        conclusion = f"{len(qualified_questions)} 个问题达到记录条件。"
    elif completed_questions == 0 and results and not has_successful_answer:
        conclusion = "平台问题尚未发送，当前没有达标记录。"
    elif all_questions_finished and unknown_count == 0:
        conclusion = "本次没有问题达到记录条件。"
    elif all_questions_finished:
        conclusion = f"检查已结束，尚未核实到符合条件的问题；{unknown_count} 个平台结果的引用核对未完成。"
    else:
        conclusion = "目前还没有问题达到记录条件，检测仍在进行。"

    lines = [
        f"# {_markdown(brand)} GEO 引用监测记录",
        "",
        f"记录时间：{_time_label(generated_at)}。",
        "",
        f"**结论：{conclusion}**",
        "",
        "达标指同一平台同时提及品牌并引用所提供文章；下方保留全部问题的回答、来源与核查依据。",
        "",
        "## 本次概览",
        "",
        "| 指标 | 结果 |",
        "| --- | --- |",
        f"| 达到记录条件的问题 | {len(qualified_questions)}/{total_questions}（{question_rate or 0}%） |",
        f"| 已完成明确引用核对的平台结果 | {known_count}/{len(all_checks)} |",
        f"| 尚未完成引用核对的平台结果 | {unknown_count} |",
    ]
    lines.extend(["", "## 本次核对的目标文章", ""])
    for index, (url, (title, _)) in enumerate(articles.items(), 1):
        lines.extend([f"文章 {index}：{_named_link(title, url)}", ""])

    platform_metrics = []
    for engine, name in _ENGINE_NAMES.items():
        selected = [observations[question][engine] for question in questions]
        brand_total = sum(item["brand"] is not None for item in selected)
        brand_count = sum(item["brand"] is True for item in selected)
        citation_total = sum(item["citation"] != "uncertain" for item in selected)
        citation_count = sum(item["citation"] == "cited" for item in selected)
        platform_metrics.append({
            "name": name,
            "brand": {"count": brand_count, "total": brand_total},
            "citation": {"count": citation_count, "total": citation_total},
        })

    if questions:
        lines.extend([
            "",
            "## 各平台表现（全部问题）",
            "",
            "统计全部问题，品牌提及与目标文章引用分别按已完成的对应判定计算。",
            "",
            "| 平台 | 品牌提及 | 目标文章引用 |",
            "| --- | --- | --- |",
        ])
        for metric in platform_metrics:
            mention = metric["brand"]
            citation = metric["citation"]
            mention_rate = _percentage(mention["count"], mention["total"])
            citation_rate = _percentage(citation["count"], citation["total"])
            mention_label = (f"{mention['count']}/{mention['total']}（{mention_rate}%）"
                             if mention_rate is not None else "暂无数据（0/0）")
            citation_label = (f"{citation['count']}/{citation['total']}（{citation_rate}%）"
                              if citation_rate is not None else "暂无数据（0/0）")
            lines.append(f"| {metric['name']} | {mention_label} | {citation_label} |")

        lines.extend(_brand_ranking_lines(config, results))
        lines.extend([
            "",
            "## 全部问题核查明细",
            "",
            "下表保留全部问题；品牌是否提及、目标文章是否引用分别列出。",
            "",
            "| 问题 | 平台 | 品牌提及 | 目标文章引用 | 核查到的引用来源 |",
            "| --- | --- | --- | --- | --- |",
        ])
        for number, question in enumerate(questions, 1):
            for engine, item in observations[question].items():
                brand_state = ("已提及" if item["brand"] is True else
                               "未提及" if item["brand"] is False else "待核对")
                citation_state = {
                    "cited": "已引用", "not_cited": "未引用", "uncertain": "待核对",
                }[item["citation"]]
                if item["matches"]:
                    citation_state += "（文章 " + "、".join(
                        str(article_numbers[url]) for url in item["matches"]
                    ) + "）"
                sources = "、".join(
                    _named_link(f"来源 {index}", url)
                    for index, url in enumerate(item["sources"], 1)
                ) or "—"
                lines.append(
                    f"| 问题 {number}：{_markdown(question)} | {_ENGINE_NAMES[engine]} "
                    f"| {brand_state} | {citation_state} | {sources} |"
                )

        lines.extend(["", "## 问题引用排名与品牌评价", ""])
        sentiment_labels = {
            "positive": "正面", "neutral": "中性", "negative": "负面", "mixed": "褒贬混合",
        }
        for number, question in enumerate(questions, 1):
            source_rows: dict[str, dict[str, set]] = {}
            page_rows: dict[str, dict] = {}
            successful_platforms = 0
            incomplete_platforms = 0
            unknown_collection_platforms = 0
            article_counts: dict[str, dict[str, set]] = {
                url: {"platforms": set(), "citations": set()} for url in articles
            }
            for engine, item in observations[question].items():
                rows = grouped[question][engine]
                successful = [row for row in rows if not row.get("error")
                              and isinstance(row.get("answer"), str) and row["answer"].strip()]
                if not successful:
                    continue
                successful_platforms += 1
                row = successful[0]
                collection = row.get("citation_collection")
                if isinstance(collection, dict) and collection.get("complete") is False:
                    incomplete_platforms += 1
                elif not isinstance(collection, dict) or collection.get("complete") is not True:
                    unknown_collection_platforms += 1

                citations = row.get("citations")
                citations = citations if isinstance(citations, list) else []
                for citation in citations:
                    if not isinstance(citation, dict):
                        continue
                    citation_url = _safe_http_url(citation.get("url"))
                    site = _source_site(citation_url) if citation_url else None
                    if not citation_url or not site:
                        continue
                    site_row = source_rows.setdefault(site, {"platforms": set(), "citations": set()})
                    site_row["platforms"].add(engine)
                    site_row["citations"].add((engine, citation_url))
                    page_row = page_rows.setdefault(citation_url, {
                        "title": _plain(citation.get("title")) or citation_url, "platforms": set(),
                    })
                    if page_row["title"] == citation_url and _plain(citation.get("title")):
                        page_row["title"] = _plain(citation["title"])
                    page_row["platforms"].add(engine)

                for article_url, citation_url in item["matched_citations"]:
                    article_counts[article_url]["platforms"].add(engine)
                    article_counts[article_url]["citations"].add((engine, citation_url))
                # Older saved results lack citation-to-article pairs. Preserve the
                # AI-confirmed article hit without inventing a multi-article mapping.
                if item["matches"] and not item["matched_citations"]:
                    for article_url in item["matches"]:
                        article_counts[article_url]["platforms"].add(engine)
                        if len(item["matches"]) == 1:
                            article_counts[article_url]["citations"].update(
                                (engine, url) for url in item["sources"]
                            )

            complete_platforms = successful_platforms - incomplete_platforms - unknown_collection_platforms
            lines.extend([
                f"### 问题 {number}：{_markdown(question)}",
                "",
                (f"引用采集状态：已取得回答 {successful_platforms}/5 个平台，其中完整 {complete_platforms} 个、"
                 f"不完整 {incomplete_platforms} 个、未报告完整度 {unknown_collection_platforms} 个；"
                 "只统计已采集到的来源，不把未出现的平台计作未引用。"),
                "",
                "#### 目标文章排名",
                "",
                "按 AI 确认引用的平台数排序，并列时按确认的引用链接数排序。",
                "",
                "| 排名 | 目标文章 | AI 确认引用的平台数 | AI 确认引用链接数 |",
                "| --- | --- | ---: | ---: |",
            ])
            ranked_articles = sorted(
                ((url, counts) for url, counts in article_counts.items() if counts["platforms"]),
                key=lambda entry: (-len(entry[1]["platforms"]), -len(entry[1]["citations"]),
                                   list(articles).index(entry[0])),
            )
            for rank, (url, counts) in enumerate(ranked_articles, 1):
                title = articles[url][0]
                lines.append(
                    f"| {rank} | {_named_link(title, url)} | "
                    f"{len(counts['platforms'])} | {len(counts['citations'])} |"
                )
            if not ranked_articles:
                lines.append("| — | 本题尚无 AI 确认引用的目标文章 | 0 | 0 |")

            ranked_sites = sorted(
                source_rows.items(),
                key=lambda entry: (-len(entry[1]["platforms"]), -len(entry[1]["citations"]), entry[0]),
            )
            lines.extend([
                "",
                "#### 来源网站排名",
                "",
                "按引用平台数排序，并列时按链接数排序。同一平台的同一网址只计一次；覆盖率以已取得回答的平台为分母。",
                "",
                "| 排名 | 来源网站 | 引用平台数 | 引用出现次数（平台内同网址去重） | 平台覆盖率 |",
                "| --- | --- | ---: | ---: | ---: |",
            ])
            for rank, (site, counts) in enumerate(ranked_sites, 1):
                lines.append(
                    f"| {rank} | {_named_link(site, f'https://{site}')} | "
                    f"{len(counts['platforms'])} | {len(counts['citations'])} | "
                    f"{len(counts['platforms'])}/{successful_platforms}（{_percentage(len(counts['platforms']), successful_platforms) or 0}%） |"
                )
            if not ranked_sites:
                lines.append("| — | 本题没有采集到可排名的来源链接 | 0 | 0 | — |")

            lines.extend([
                "", "#### 来源文章排名", "",
                "按引用该文章的平台数排序；同一平台重复出现同一网址只计一次，并列时按来源网址排序。",
                "", "| 排名 | 来源文章 | 来源网站 | 引用平台数 | 覆盖率（已取得回答的平台） | 引用平台 |",
                "| --- | --- | --- | ---: | ---: | --- |",
            ])
            ranked_pages = sorted(page_rows.items(), key=lambda entry: (-len(entry[1]["platforms"]), entry[0]))
            for rank, (url, page) in enumerate(ranked_pages, 1):
                platforms = "、".join(_ENGINE_NAMES[e] for e in _ENGINE_NAMES if e in page["platforms"])
                count = len(page["platforms"])
                lines.append(f"| {rank} | {_named_link(page['title'], url)} | {_markdown(_source_site(url))} | "
                             f"{count} | {count}/{successful_platforms}（{_percentage(count, successful_platforms) or 0}%） | {platforms} |")
            if not ranked_pages:
                lines.append("| — | 本题没有采集到可排名的来源文章 | — | 0 | — | — |")

            assessments = [
                (engine, item["assessment"])
                for engine, item in observations[question].items()
                if item["brand"] is True and isinstance(item["assessment"], dict)
            ]
            if assessments:
                lines.extend([
                    "",
                    "#### 品牌评价与标签",
                    "",
                    "仅展示 AI 判定回答中提及品牌的平台；引号内容摘自对应平台回答。",
                    "",
                    "| 平台 | 评价倾向 | AI 归纳标签 | 回答依据摘录 |",
                    "| --- | --- | --- | --- |",
                ])
                for engine, assessment in assessments:
                    sentiment = sentiment_labels.get(assessment["sentiment"], "待分析")
                    tags = "、".join(_markdown(tag) for tag in assessment["tags"]) or "仅提及，未归纳出评价标签"
                    quote = _markdown(assessment["quote"]) or "—"
                    lines.append(
                        f"| {_ENGINE_NAMES[engine]} | {sentiment} | {tags} | “{quote}” |"
                    )

    lines.extend(_audit_markdown(questions, grouped))
    return "\n".join(lines) + "\n"
