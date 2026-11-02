"""admin_crawl — AI/LLM 爬虫日志分析(仅 admin,只读).

只读共享库里的快照(由 prod 系统 crontab 每天写一次,读的是 vigilath 正式环境
nginx 日志).端点**只读不算** —— prod / test 都查同一行,test 看到的就是正式
环境数据,且 test 永远不会用自己的日志覆盖正式数据.

快照生成见 geo/services/crawl_snapshot.py(prod crontab 调 __main__).
"""

from fastapi import APIRouter, Depends

from geo.api.auth import require_admin
from geo.services.crawl_snapshot import _EMPTY, _LOG_GLOB, load_snapshot

router = APIRouter(prefix="/admin/crawl-analysis")


@router.get("")
def get_crawl_analysis(_admin=Depends(require_admin)):
    """返回共享库里的 AI 爬虫分析快照(正式环境数据)."""
    snap = load_snapshot()
    if snap is not None:
        return snap
    # 还没有快照(prod cron 没跑过)— 返回空结构,前端显示"暂无数据".
    return {**_EMPTY, "log_glob": _LOG_GLOB, "generated_at": None}
