"""组件级评测 —— 无 LLM、确定性,做 CI 回归闸门。

只测**机制层**(route_line + 业务线工具隔离),不调模型、不连库,毫秒级:
1. route_line(问句) 是否判到期望业务线;
2. 被路由到的那条线,其工具集是否**包含** expect_tools、**不含** forbid_tools。

第 2 条是隔离机制的硬保证:即便模型想越线调 GEO 写工具,该线工具集里根本没有它 → 够不到。
改 route_line 关键词或 _line_tools 分组导致退步,这里立刻红。

运行(用 agent venv,因为 import 链会拉到 pydantic-ai):
    /home/ubuntu/Dev/geo/agent-venv/bin/python -m pytest backend/geo/agent/eval/test_routing.py -q
"""
from __future__ import annotations

import pytest

from geo.agent.eval.dataset import CASES
from geo.agent.agent import route_line, _line_tools, _GEO_READ, _GEO_WRITE


def _toolset_names(line: str) -> set[str]:
    """该业务线对外 embed agent(can_write=True,不含 publish)实际能加载的工具名集合。"""
    return {getattr(t, "__name__", str(t)) for t in _line_tools(line, can_write=True, include_publish=False)}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_route_line(case):
    assert route_line(case.utterance) == case.line, (
        f"[{case.id}] route_line 判错:期望 {case.line},得到 {route_line(case.utterance)} —— {case.utterance!r}"
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_expected_tools_reachable(case):
    """期望工具必须在被路由到的线的工具集内,否则模型根本够不到、不可能调成功。"""
    names = _toolset_names(case.line)
    missing = [t for t in case.expect_tools if t not in names]
    assert not missing, f"[{case.id}] 期望工具不在 {case.line} 线工具集内(机制上够不到):{missing}"


# GEO 全部工具名(舆情线必须一个都够不到 —— 这是跨线隔离的硬保证)
_GEO_ALL = {getattr(t, "__name__", str(t)) for t in (_GEO_READ + _GEO_WRITE)}


@pytest.mark.parametrize("case", [c for c in CASES if c.line == "sentiment"], ids=lambda c: c.id)
def test_sentiment_line_has_no_geo_tools(case):
    """跨线隔离硬保证:舆情线工具集里**不含任何 GEO 工具**,模型机制上够不到 GEO 写动作。

    注意:per-case 的 forbid_tools 是**行为级**(模型不该"调用",如查看类问句别去 draft_articles),
    而 draft_articles/create_topic 本就合法存在于 GEO 线 —— 那类断言只能在 run_eval(端到端)做。
    """
    leaked = _toolset_names("sentiment") & _GEO_ALL
    assert not leaked, f"[{case.id}] 跨线隔离失效:舆情线竟加载到 GEO 工具 {leaked}"


def test_publish_never_in_embed():
    """对外 embed agent 永不含 publish_drafts(真实外发不可对外可达)。"""
    for line in ("geo", "sentiment", "both"):
        assert "publish_drafts" not in _toolset_names(line), f"{line} 线对外竟暴露 publish_drafts"
