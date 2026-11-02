"""媒介星对接冒烟测试(测试媒体走通全链路)。

测试资源(媒介星提供):
    新闻媒体 mid=4192,自媒体 mid=2517

用法(在 backend/ 下,凭据配在 .env 的 MJX_SECRET_ID / MJX_SECRET_KEY):
    ./venv/bin/python scripts/mjx_smoke_test.py                 # 只读:余额 + 两个测试媒体信息
    ./venv/bin/python scripts/mjx_smoke_test.py --create        # 真下单(需 MJX_PUBLISH_ENABLED=1)
    ./venv/bin/python scripts/mjx_smoke_test.py --query no1,no2 # 查订单状态

--create 默认只投测试媒体(4192/2517),订单号格式 vig-smoke-{media|wmedia}-{时间戳},
saling_price 取媒体列表里的报价(可 --price 覆盖)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from geo.services.mjx_client import MjxClient, MjxApiError, MjxError, ORDER_STATUS

TEST_MEDIA_ID = 4192    # 新闻媒体(测试)
TEST_WMEDIA_ID = 2517   # 自媒体(测试)

TEST_TITLE = "Vigilath 对接冒烟测试稿件(请忽略)"


def dump(label: str, data) -> None:
    print(f"\n===== {label} =====")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def show_readonly(c: MjxClient) -> tuple[dict | None, dict | None]:
    """余额 + 两个测试媒体的档案;返回 (媒体4192, 自媒体2517) 的记录。"""
    dump("1. 余额 userInfo", await c.user_info())

    media = None
    data = await c.media_list(media_id=TEST_MEDIA_ID, page=1, limit=200)
    rows = data if isinstance(data, list) else [data] if data else []
    for r in rows:
        if str(r.get("id")) == str(TEST_MEDIA_ID):
            media = r
    dump(f"2. 新闻媒体 id={TEST_MEDIA_ID}(media_lst)", media or rows[:3] or "未返回")

    wmedia = None
    page = 1
    while page <= 30 and wmedia is None:  # 自媒体列表无 id 过滤,翻页查找
        wdata = await c.wmedia_list(page=page, limit=200)
        wrows = wdata if isinstance(wdata, list) else []
        if not wrows:
            break
        for r in wrows:
            if str(r.get("id")) == str(TEST_WMEDIA_ID):
                wmedia = r
                break
        page += 1
    dump(f"3. 自媒体 id={TEST_WMEDIA_ID}(wmedia_lst 翻了 {page} 页)", wmedia or "未找到")
    return media, wmedia


async def create_orders(c: MjxClient, preview_url: str, price_override: str | None) -> list[str]:
    if price_override:
        # 指定售价时跳过列表查询(自媒体列表无 id 过滤,翻页连发请求会触发对方 WAF 封禁)
        media, wmedia = None, None
    else:
        media, wmedia = await show_readonly(c)
    nos: list[str] = []
    ts = int(time.time())

    plans = [
        ("media", TEST_MEDIA_ID, media, "API测试", c.create_media_order),
        ("wmedia", TEST_WMEDIA_ID, wmedia, "自媒体API测试", c.create_wmedia_order),
    ]
    for kind, mid, row, fallback_name, create in plans:
        price = price_override or str((row or {}).get("price") or "0")
        name = (row or {}).get("media_name") or (row or {}).get("wemedia_name") or fallback_name
        no = f"vig-smoke-{kind}-{ts}"
        print(f"\n>>> 下单 {kind} mid={mid} media_name={name} no={no} saling_price={price}")
        try:
            data = await create(
                title=TEST_TITLE,
                preview_url=preview_url,
                mid=mid,
                no=no,
                remark="对接冒烟测试,无需真实出稿",
                saling_price=price,
                media_name=name,
            )
            print(f"    创建成功 data={data!r}")
            nos.append(no)
        except MjxApiError as e:
            print(f"    创建失败 code={e.code} msg={e}")
        except MjxError as e:
            print(f"    请求异常(继续下一个): {e}")
    return nos


async def query_orders(c: MjxClient, nos: list[str]) -> None:
    for label, fn in (("新闻订单", c.query_media_order), ("自媒体订单", c.query_wmedia_order)):
        try:
            data = await fn(nos)
            rows = data if isinstance(data, list) else [data] if data else []
            for r in rows:
                if isinstance(r, dict) and "status" in r:
                    r["status_label"] = ORDER_STATUS.get(str(r["status"]), "?")
            dump(f"查询 {label} nostr={','.join(nos)}", rows or "无记录")
        except MjxApiError as e:
            print(f"\n查询 {label} 失败 code={e.code} msg={e}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--create", action="store_true", help="真实下单到测试媒体(付费闸需开)")
    ap.add_argument("--query", default=None, help="查订单状态,逗号分隔订单号")
    ap.add_argument("--preview-url", default="https://www.vigilath.com/", help="稿件预览链接")
    ap.add_argument("--price", default=None, help="覆盖 saling_price(默认用媒体报价)")
    args = ap.parse_args()

    c = MjxClient()  # 缺密钥这里直接 MjxConfigError

    if args.query:
        await query_orders(c, [n.strip() for n in args.query.split(",") if n.strip()])
        return
    if args.create:
        nos = await create_orders(c, args.preview_url, args.price)
        if nos:
            print("\n下单完成,等 5s 查一次状态…")
            await asyncio.sleep(5)
            await query_orders(c, nos)
            print(f"\n后续手动查状态:--query {','.join(nos)}")
        return
    await show_readonly(c)


if __name__ == "__main__":
    asyncio.run(main())
