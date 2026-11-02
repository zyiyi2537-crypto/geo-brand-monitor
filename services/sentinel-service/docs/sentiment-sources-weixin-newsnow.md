# 舆情数据源扩展:weixin_album + newsnow

> 文档日期:2026-05-17
> 范围:本轮新接的两个数据源(微信公众号合集枚举、newsnow 热榜聚合)及其在 sentinel-service 中的能力定位
> 相关文档:[Sentinel 当前集成说明](../../../docs/integrations/sentinel.md)、
> [sentiment-architecture-v2.md](./sentiment-architecture-v2.md)(历史目标设计)

---

## 一、本次扩展前后对比

### 扩展前(2026-04 状态)

| 类别 | crawler 数 | 代表源 | 覆盖问题 |
|------|---|---|---|
| 财经直爬 | 15 | eastmoney(股吧+资讯+研报+公告+行业)、xueqiu、gelonghui、wallstreetcn、yicai、kr36、cls、sina | ✅ 财经强 |
| 搜索引擎 | 4 | cnbing / baidu / sogou / ddg(EC2 代理) | ✅ 关键词全网搜,但 sogou 微信窗口仅 ~24h |
| 微信内容 | 1 | 只有 sogou search → mp.weixin 命中 | ❌ 历史深度 0,KOL 盯防 0 |
| 群众反应面 | 0 | — | ❌ 微博/知乎/抖音/虎扑 等盲区 |
| 实时热点 | 0 | — | ❌ 突发事件感知靠人 |

### 扩展后(2026-05-17 起)

| 类别 | crawler 数 | 新增源 | 解决了什么 |
|------|---|---|---|
| 财经直爬 | 15 | 不变 | — |
| 搜索引擎 | 4 | 不变 | — |
| **微信内容** | +1 | `weixin_album` | 按号枚举合集全量历史(年级深度) |
| **群众反应面** | +1 | `newsnow` (13 站热榜) | 微博/知乎/抖音/虎扑/今日头条/虎嗅/财联社等 |
| **实时热点** | (内含) | `newsnow` 2 分钟刷新 | 突发热点分钟级感知 |

---

## 二、weixin_album:微信公众号合集枚举

### 技术细节

| 项 | 值 |
|---|---|
| 数据源 | `mp.weixin.qq.com/mp/appmsgalbum?action=getalbum` |
| 认证 | 无 cookie,iPhone MicroMessenger UA + cursor 翻页 |
| 输入 | 合集 URL(管理员手动粘) |
| 单页 | ≤20 篇,1-3s 随机间隔避免风控 |
| 正文 hydration | 三策略 fallback:`<meta description>` / `#js_content` / `.rich_media_content`,**取最长** |
| 入库字段 | source / post_id / symbol(=album_id) / title / url / content / publish_time |
| 实测吞吐 | 30 篇含正文 ~74 秒;500 篇 ~13 分钟 |

### 实测覆盖(2026-05-17 vm02)

| 合集 | 篇数 | 平均正文字数 | 主题 |
|---|---|---|---|
| 简单医行 案例分享 | 999 | 1716 字 | 中医外治法案例(meta description 富 → swiper 格式) |
| 极客公园 | 7 | 3306 字 | 长文科技报道(#js_content 富 → 单图文格式) |
| AI 日报 | 10 | 2883 字 | AI 日榜聚合 |
| AI Guard | 10 | 528 字 | AI 安全治理周报(政策导向) |

### ✅ 能力

- 按号"**已知 KOL 深度盯防**":年级历史 + 周级别增量
- 服务端裸跑:无 cookie / 无浏览器
- 正文 1000-5000 字真实可读,LLM 可直接做 entity/sentiment 抽取
- 与现有 sentinel pipeline 无缝整合:配在 `SentimentAccountORM.weixin_album_urls_json`,空配置自动跳过

### ❌ 限制

- **不支持关键词搜索**:getalbum 接口不收 query 参数(已扒源码确认)
- **覆盖率上限低**:作者必须手动建合集才有 album_id,**粗估 <30% 的公众号有合集**
- **遗漏合集外文章**:作者未归类的文章拿不到
- **无互动指标**:接口不返阅读量/在看/点赞,是微信生态通病
- **无自动发现机制**:必须管理员粘 URL(手机微信里复制最稳)
- **滞后实时**:合集是策展产物,作者手动归类后才出现

### 一句话定位

> 对"**已知的几个号**"做"**长期历史**"深度盯防,不替代关键词全网搜。

---

## 三、newsnow:13 站热榜聚合

### 技术细节

| 项 | 值 |
|---|---|
| 部署形态 | `geo-newsnow.service` systemd,Node/Nitro,端口 4444 |
| 代码 | `/opt/newsnow`(github.com/ourongxing/newsnow,MIT 协议) |
| 接入 | sentinel-service `.env` 配 `NEWSNOW_BASE_URL=http://127.0.0.1:4444` |
| 数据 API | `/api/s?id=<source>` 返 JSON |
| 站列表 | 42 个源,其中 vm02 国内机房**可用 ~30 个**(海外 v2ex/github/HN/reddit fail) |
| 数据 shape | `id / title / url / mobileUrl / extra`,**无时间戳 / 无正文 / 无阅读量** |
| 刷新 | 2 分钟最小窗口 + 30 分钟服务端缓存 |
| 入库前过滤 | 本地按 `target + aliases + keywords` 取并集做 title 子串过滤 |

### 实测覆盖(2026-05-17 vm02)

| 类型 | 可用源 | 备注 |
|---|---|---|
| **社交/UGC** | weibo, zhihu, douyin, kuaishou, bilibili, tieba, douban, hupu | 微博公开热搜免 cookie 即拿到 50 条 |
| **科技/资讯** | ithome, ghxi, juejin, smzdm, sspai | 国内站直连佳 |
| **财经** | xueqiu, gelonghui, wallstreetcn, cls, jin10, fastbull | 与现有 15 爬虫部分重复,选择性接入 |
| **门户** | toutiao, baidu, thepaper, ifeng, tencent, sputniknewscn, zaobao | |
| **海外** | v2ex, hackernews, github, reddit, producthunt, solidot | ❌ 国内机房 fetch 全 timeout,**已确认放弃** |

### ✅ 能力

- 一站拿到 13+ 国内热榜的实时快照
- 突发热点 2-5 分钟级感知
- 填补**群众反应面**:微博热搜、知乎热榜、虎扑、抖音(财经爬虫盲区)
- 自托管 JSON API:与 sentinel-service 内网通信,免第三方 SaaS
- 失败优雅:某源 timeout 不影响其他源
- MIT 协议,无外部依赖、无配额

### ❌ 限制

- **数据极薄**:只有 title + url,**没有正文 / 时间戳 / 阅读量**
- **不能服务端按品牌搜**:只能拿"每站当前热榜",再本地过滤
- **无历史**:纯快照,不持久化就消失
- **关键词命中靠运气**:小众 B2B 品牌词(如"世纪互联")可能 0 命中,**只有热门词(宁德时代/算力/AI/品牌大事件)才高命中**
- **海外源国内不可用**:vm02 → v2ex.com / HN / GitHub 全 timeout(需独立 EC2 代理,**目前未做**)
- **每站只返 30-50 条 hot**:深度排名外抓不到
- **部分源需 cookie**:微博 SUB / 抖音 / B 站,过期得手动续

### 一句话定位

> 在"**全网未知热点**"冒头时"**第一时间发现**",不替代深度爬取也不替代正文分析。

---

## 四、舆情监控标准 vs 当前能力(扩展后)

| 标准维度 | 扩展前 | 扩展后 | 关键差距说明 |
|---|---|---|---|
| 覆盖广度 | 65% | **85%** | 加微信深度 + 群众反应面;海外缺失 |
| 实时性 | sogou 24h | **分钟级** | newsnow 2 分钟刷新 |
| 历史深度 | 各爬虫弱 | **年级**(KOL) | 仅限有合集的公众号 |
| 关键词检索 | 70% | 70% | 仍靠 sogou + 现有 15 爬虫,新源不增强这一项 |
| 正文获取 | 部分有 | **75%** | weixin 补 1000-5000 字,newsnow 仍只标题 |
| 互动指标 | 40% | **40%**(没变) | 微信/微博/抖音都拿不到,行业天花板 |
| 情绪/事件极性 | 95%(LLM) | 95%(LLM) | 不受数据源影响,analyze 阶段统一打 |
| 多源去重 | 80% | 80% | post_id (source, id) 双键主键,跨源同新闻不冲突 |
| 媒体方 vs 群众方 | 55% | **85%** | 群众反应面从 0 补到 6 站 |

---

## 五、实战配置(管理员视角)

### 5.1 给一个 sentiment account 加 weixin_album

1. 手机微信打开目标公众号 → 任意文章 → 顶部"合集"banner → 右上角 ··· → 复制链接
2. 拿到的 URL 形如:`https://mp.weixin.qq.com/mp/appmsgalbum?__biz=Mzxxx==&action=getalbum&album_id=NNNNNN&scene=21`
3. 浏览器登 GEO,账号编辑页 → 扩展数据源 → "微信公众号合集 URL" → 粘进去
4. 保存并立即跑一次 → ~13 分钟后 posts 表出现 `source='weixin_album'`

### 5.2 给一个 sentiment account 加 newsnow

1. 账号编辑页 → 扩展数据源 → "NewsNow 热榜源订阅"
2. 推荐组合:`weibo,zhihu,toutiao,36kr,huxiu,ithome,jin10,wallstreetcn,cls`(国内可用 + 财经科技覆盖)
3. **关键**:`keywords` 必须包含品牌词 + 行业词。仅品牌词太精确,命中往往为 0
   - 反例:`["世纪互联","vnet"]` → 命中 0
   - 正例:`["世纪互联","vnet","数据中心","IDC","AIDC","算力"]` → 命中 4(含财联社研报)
4. 保存并立即跑一次 → 几分钟后 posts 表出现 `source='newsnow:weibo'` 等

### 5.3 微博完整热搜(可选,需 cookie)

`/opt/newsnow/.env.server` 加一行:
```
WEIBO_COOKIE=SUB=<你浏览器 weibo.com 登录后从 DevTools 抠出来的 SUB 值>
```
然后 `systemctl restart geo-newsnow.service`。无 cookie 也能拿前 50 条,有 cookie 拿全量 50+。

---

## 六、已知盲区(行业天花板,非本系统 bug)

| 盲区 | 影响 | 备选方案 | 决策 |
|---|---|---|---|
| 微信全网按品牌词实时搜 | 中等 | sogou 仅 24h 窗口,无替代 | **行业天花板**,只能接受 |
| 阅读量 / 转发 / 点赞 | 高 | 微博/知乎要登录态,微信无接口 | **要互动数据就买 SaaS**(WiseHub / 知微) |
| 抖音 / B 站短视频字幕 | 高 | OCR + ASR 流水线 | **重投入**,放到长期路线图 |
| 海外源(V2EX/HN/Reddit/GitHub) | 低-中 | 独立出口代理 | **已评估暂缓** |
| 小红书 | 中 | 反爬严,sogou 索引浅,需专门 client | **未做**,P2 |
| 微信非合集文章 | 中 | 公众号文章列表接口已加密 | sogou 兜底,**行业天花板** |

---

## 七、路线图建议

### P1(短期,1-2 周价值高)

- **newsnow 过滤词独立成 ORM 字段**(`newsnow_filter_keywords_json`):目前与品牌 `keywords` 混用,导致品牌词太精确时命中 0。独立后管理员可"行业词只过滤 newsnow,品牌词管全 crawler"
- **weixin_album 自动发现工具**:给定公众号 ID,探测它建过哪些合集 → 减少管理员粘 URL 工作量
- **newsnow source 健康监控**:某站连续 1h fail 时告警(目前 fail-silent)

### P2(中期)

- 小红书 client(反爬攻坚,~1-2 周工)
- newsnow 海外源走代理(需要先有通用 HTTP forwarder 基础设施)
- 短视频 OCR/ASR(只抓字幕,不下视频)

### P3(长期 / 不做)

- 微信全网按品牌词实时搜(腾讯生态围墙,**不可能**)
- 自建阅读量统计(平台都加密了,**不可能**)

---

## 八、文件 / 服务清单(本轮新增)

### Backend / sentinel-service

- `services/sentinel-service/crawler/weixin_album.py` 新增(~220 行)
- `services/sentinel-service/crawler/newsnow_hub.py` 新增(~130 行)
- `services/sentinel-service/service.py` 加 `/run-crawl-weixin-album` + `/run-crawl-newsnow` 路由
- `backend/geo/services/sentinel_client.py` 加 `crawl_weixin_album()` / `crawl_newsnow()`
- `backend/geo/services/sentiment_pipeline.py` `crawler_tasks` 列表条件追加两源
- `backend/geo/models/sentiment.py` ORM 加 `weixin_album_urls_json` / `newsnow_sources_json`
- `backend/alembic/versions/a8c5d2f1e0b3_*.py` 加两列 migration

### Frontend

- `frontend/src/types/sentiment.ts` Account 类型加两字段
- `frontend/src/pages/Account/BrandSettingsTab.tsx` 扩展数据源区块
- `frontend/src/mocks/sentiment.ts` Mock 同步

### Infra

- `docker-compose.yml` 加 newsnow service(开发环境用)
- `/etc/systemd/system/geo-newsnow.service`(测试环境 vm02)
- `/opt/newsnow/.env.server`(随机 JWT_SECRET,占位 OAuth)

### 测试环境部署

测试环境细节不属于版本库文档；部署时从受保护的运维配置获取。
