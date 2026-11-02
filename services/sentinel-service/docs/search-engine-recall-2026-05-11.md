# 搜索引擎召回 + 字段可得性 调研汇总

> 调研时间:2026-05-11
> 关键词样本:世纪互联(VNET)
> 目标平台:weibo.com / sina.com / toutiao.com / mp.weixin.qq.com
> 搜索引擎样本:DDG / Google / Baidu / Bing / Sogou / 360 / Brave / 神马
> 时间窗:24h / 7d / 31d
> 运行环境:US AWS EC2 出口(本机 IP 对国内站普遍风控)

---

## 表 A · 八个搜索引擎横向对比

| 引擎 | 调用方式 | 要 key 吗 | 配额 | 时间窗参数 | 返回 date | 数字可信 | site: 召回深度 | 本机可达 | 进生产推荐 |
|---|---|---|---|---|---|---|---|---|---|
| **DDG ddgs lib** | 库 | 否 | backend pool 不稳 | `timelimit=d/w/m` | ❌ 无 | ❌ 噪音多 | 浅(6~12) | ✅ | 🟡 兜底 |
| **DDG 浏览器网页** | 浏览器 | 否 | — | `df=d/w/m` | ❌ 无 | ⚠️ 虚高 | UI 估计值 | ❌ 国内 IP 风控 | ❌ |
| **Google Serper.dev** | API | ✅ X-API-KEY | 2500 次免费,`num≤20` | `tbs=qdr:d/w/m` | ⚠️ 部分 | ⚠️ silent widening | 单 query 20-40 | ✅ | ✅ 跨境首选 |
| **Google CSE 官方** | API | ✅ 双 key | 100/天免费 | `dateRestrict=d1/w1/m1` | ⚠️ 部分 | ⚠️ 同上 | 最多 100 | ✅ | 🟡 备用 |
| **Google 浏览器网页** | 浏览器 | 否 | — | `tbs=qdr:d/w/m` | ⚠️ | ⚠️ | UI 估计值 | ❌ 429 /sorry/ | ❌ |
| **Baidu Qianfan API** | API | ✅ Bearer bce-v3 | 收费 ~1 元/千次 | ⚠️ 服务端不可信,**客户端按 date 过滤** | ✅ 稳定 YYYY-MM-DD | ✅ 干净 | site: 硬上限 ~31-50 | ✅ | ✅ 国内首选 |
| **Baidu 浏览器网页** | 浏览器 | 否 | — | `gpc=stf=<lo>,<hi>` | ⚠️ | ⚠️ | UI 估计值 | ❌ 安全验证 | ❌ |
| **Bing Web Search API** | API | ✅ Azure | 1000/月免费 | `freshness=Day/Week/Month` | ⚠️ 部分 | ⚠️ | 单 query ≤50 × 5 页 | ✅(给 key) | 🟡 英文备份 |
| **Bing cn.bing.com 网页** | 浏览器 | 否 | — | `filters=ex1:"ez1/ez2/ez3"` | ⚠️ | ⚠️ | UI 估计值 | ❌ 302 回首页 | ❌ |
| **Sogou-微信(weixin.sogou.com)** | 网页 | 否 | — | `tsn=1/2/3` | ⚠️ | ⚠️ | 仅微信公众号 | ❌ 反爬 | ❌(CN VM + cookie 可) |
| **Sogou-Web(sogou.com/web)** | 网页 | 否 | — | 无 | ❌ | ❌ | — | ❌ antispider | ❌ |
| **360 (so.com)** | 网页 | 否 | — | `adv_ts=<lo>,<hi>` | ❌ | ❌ 数字非单调 | weibo 56/49/0 异常 | ✅ | ❌ 时间窗不真过滤 |
| **Brave Search API** | API | ✅ Token | 2000/月免费 | `freshness=pd/pw/pm` | ⚠️ 部分 | ⚠️ | 单 query ≤20 × 5 页 | ✅(给 key) | 🟡 DDG 替代 |
| **神马 (quark.sm.cn)** | 网页 | 否 | — | 无 | ❌ | ❌ | 索引无相关结果 | ✅ 但空 | ❌ |

---

## 表 B · 信息字段 × 4 个目标平台(能不能拿到)

列 = 4 个目标平台,行 = 你列的字段。每格 = 能否拿到 + 怎么拿到 + 难度。

| 信息字段 | weibo.com | mp.weixin.qq.com | toutiao.com | sina.com |
|---|---|---|---|---|
| **命中页 URL** | ✅ 搜索 API | ✅ 搜索 API | ✅ 搜索 API | ✅ 搜索 API |
| **标题** | ✅ 搜索 API | ✅ 搜索 API | ✅ 搜索 API | ✅ 搜索 API |
| **摘要(snippet)** | ✅ Qianfan ~500 字最长 | ✅ 同左 | ✅ 同左 | ✅ 同左 |
| **发布平台(域名)** | ✅ URL 反推 | ✅ | ✅ | ✅ |
| **发布时间(搜索结果)** | ✅ Qianfan `date` 字段 | ✅ 同左 | ✅ 同左 | ✅ 同左 |
| **发布时间(页面精确到分)** | ✅ 爬源 `<a class="date">` | ✅ 爬源 HTML meta | ✅ 爬源 JSON-LD | ✅ 爬源 meta |
| **发布账号 / 昵称** | ✅ 爬源 `<a class="name">` | ✅ 爬源 `rich_media_meta_link` | ✅ 爬源 JSON-LD | ⚠️ 仅有"编辑名",不是用户 |
| **作者 IP 属地** | ✅ **仅 weibo 平台暴露**,爬源 `<span>发布于 XX</span>` | ❌ 平台不显示 | ❌ 平台不显示 | ❌ 平台不显示 |
| **转发数** | ✅ 爬源 span | ❌ 无公开数字 | ✅ 爬源 JSON | ❌ 无 |
| **评论数** | ✅ 爬源 span | ❌ 无公开 | ✅ 爬源 JSON | ❌ 无 |
| **点赞数** | ✅ 爬源 span | ❌ 无公开("在看"只在公众号后台) | ✅ 爬源 JSON | ❌ 无 |
| **全文正文** | ⚠️ 短文 OK,长文需登录 | ✅ HTML 直拿 | ⚠️ `/article/` OK,`/topic/` 需 JS | ✅ 直拿 |
| **配图 / 视频 URL** | ✅ 爬源 | ✅ 爬源 | ✅ 爬源 | ✅ 爬源 |
| **评论列表** | ⚠️ 需登录态 + JS | ❌ 不开放 | ⚠️ 需 app 端,合规风险 | ❌ 无 |
| **页面位置 / 地理标签** | ⚠️ 仅签到微博有 | ❌ | ❌ | ❌ |
| **关键词时间窗过滤** | ✅ Qianfan 客户端按 date 过滤 | ✅ 同左 | ✅ 同左 | ✅ 同左 |
| **关键词严格短语匹配** | ⚠️ 必须在 title/snippet 后置过滤(搜索引擎都靠不住) | ⚠️ 同左 | ⚠️ 同左 | ⚠️ 同左 |
| **历史回溯 > 1 年** | ❌ 搜索引擎不索引 | ❌ | ❌ | ❌ |
| **实时秒级推送** | ❌ 索引延迟 1-6 小时 | ❌ | ❌ | ❌ |
| **反爬难度** | ⭐⭐⭐ 高(JS + 登录) | ⭐ 低 | ⭐⭐ 中 | ⭐ 低 |

---

## 速查清单 · 能做 / 不能做 一句话版

| 类别 | 内容 |
|---|---|
| ✅ **稳定能做** | 列 URL、标题、摘要、发布时间、平台、发布账号、转评赞(微博/头条)、全文(微信/sina/头条)、配图、按时间窗筛、严格短语后置过滤 |
| ⚠️ **看条件能做** | weibo 长文 / 评论(需登录 cookie),头条 `/topic/`(需 headless),国内机房直爬(部分需代理) |
| ❌ **平台本身就不暴露** | mp.weixin / toutiao / sina 的**作者 IP 属地**(只有微博有),微信公众号的**阅读量/点赞数**(只在后台),sina 的**转评赞**(无社交属性),所有平台的**评论列表**(全要登录,合规风险) |
| ❌ **物理限制** | 实时秒级(索引延迟 1-6h),历史 > 1 年回溯,"约 N 条"那种大数字(UI 估计值不可信) |
| ❌ **搜索引擎硬限** | Qianfan/Bing/Serper 单 site: query 都有几十条上限;Google silent widening 引号失效;DDG 数字纯噪音 |
| 🏆 **生产推荐配置** | **Baidu Qianfan**(国内深)+ **Google Serper.dev**(跨境)+ **DDG ddgs**(兜底);Bing/Brave 给 key 可加;Sogou/360/神马**不进** |

---

## 附 · 实测脚本

- `/tmp/api_search_counts.py` — DDG instant / Baidu Qianfan / Google CSE / Serper.dev
- `/tmp/more_engines.py` — Bing / Sogou-Weixin / Sogou-Web / 360 / Brave / 神马
- `/tmp/dump_results.py` — Qianfan + ddgs 真实命中明细 dump
- `/tmp/verify_ddg_html.py` — DDG 浏览器同源端点 (html.duckduckgo.com)

## 附 · 三组数据落差(浏览器手数 vs API vs 真实命中,keyword = `世纪互联`)

| 平台 | 浏览器手数 DDG/Google/Baidu (24h/7d/31d) | API ddgs/serper/Qianfan (24h/7d/31d) | 去噪后真实命中(31d) |
|---|---|---|---:|
| weibo.com | 7/64/228 ‖ 11/124/449 ‖ 0/25/25 | 4/12/12 ‖ 0/0/2 ‖ 0/1/2 | 2(高盛买入 + DYXnet 官方) |
| sina.com | 0/0/0 ‖ 0/0/4 ‖ 0/0/0 | 6/6/6 ‖ 0/0/0 ‖ 0/0/0 | 0(全是 CenturyLink Field 同名) |
| toutiao.com | 0/10/10 ‖ 0/1/34 ‖ 0/4/14 | 6/6/12 ‖ 0/0/4 ‖ 0/0/0 | 2(算力涨价 + 但斌持仓) |
| mp.weixin.qq.com | 21/210/749 ‖ — ‖ 1/33/80 | 6/6/6 ‖ 0/0/0 ‖ 1/2/7 | 7(算力/IDC/早报公众号) |

落差解释:浏览器"约 N 条"是 UI 估计 + 分词假阳性;API 严格;真实命中 = API 结果再做严格短语过滤 + 去同名实体后剩下的。
