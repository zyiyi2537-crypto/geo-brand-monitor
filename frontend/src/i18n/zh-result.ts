const zhResult = {
"result": {
            "title": "GEO 检测结果",
            "resultsFor": "检查结果：",
            "progress": {
              "title": "正在检测中…",
              "elapsed": "已用时 {{seconds}} 秒",
              "hint": "请保持此页面打开",
              "almostDone": "即将完成…",
              "subtitle": {
                "default": "正在运行 25 项 GEO 全量检测",
                "compare": "多站点并排打分对比",
                "crawlTest": "测试 AI 爬虫可达性",
                "authority": "审计外部权威信号",
                "citation": "通过 Perplexity 检测 AI 引用",
                "visibility": "跨引擎可见性审计",
                "entity": "审计 AI 对该实体的认知"
              },
              "stages": {
                "default": {
                  "fetch": "抓取页面与 HTTP 头",
                  "protocols": "检测 robots、sitemap、llms.txt",
                  "structured": "解析结构化数据与 schema",
                  "content": "分析 AI 内容质量",
                  "technical": "检测技术健壮性与媒体",
                  "authority": "汇总权威与信任信号",
                  "finalize": "评分并生成报告"
                },
                "compare": {
                  "fetch": "抓取所有对比站点",
                  "parse": "解析各站点页面",
                  "score": "对 25 项 GEO 类目打分",
                  "diff": "计算类目差距",
                  "finalize": "生成对比表"
                },
                "crawlTest": {
                  "robots": "读取 robots.txt 规则",
                  "probe": "模拟 GPTBot / ClaudeBot / PerplexityBot 抓取",
                  "waf": "检测 WAF / CDN 可达性",
                  "commonCrawl": "查询 Common Crawl 索引",
                  "finalize": "汇总抓取测试结果"
                },
                "authority": {
                  "github": "检索 GitHub 提及",
                  "pkg": "查询 npm / PyPI 包登记",
                  "wiki": "查询 Wikipedia 与 Wikidata",
                  "social": "收集社交信号",
                  "finalize": "汇总权威评分"
                },
                "citation": {
                  "prepare": "生成品牌相关提问",
                  "perplexity": "调用 Perplexity AI 查询（耗时较长）",
                  "parseCites": "解析引用与来源域名",
                  "finalize": "计算引用覆盖率"
                },
                "visibility": {
                  "prepare": "生成可见性查询集",
                  "chatgpt": "调用 ChatGPT 查询（耗时较长）",
                  "perplexity": "调用 Perplexity 查询",
                  "claude": "调用 Claude 查询",
                  "classify": "归类品牌情感框架",
                  "finalize": "汇总跨引擎可见性"
                },
                "entity": {
                  "wiki": "检测 Wikipedia 词条",
                  "wikidata": "检测 Wikidata 实体",
                  "platforms": "检测平台覆盖（GitHub、IMDB 等）",
                  "llm": "多引擎 AI 识别探测",
                  "sentiment": "识别情感与叙述框架",
                  "gaps": "识别内容缺口",
                  "finalize": "汇总实体 GEO 评分"
                }
              }
            },
            "checks": {
              "https": {
                "uses_https": "站点已启用 HTTPS",
                "not_https": "站点未使用 HTTPS——AI 引擎更偏好安全站点"
              },
              "robots": {
                "not_found": "{{url}} 找不到 robots.txt",
                "found": "robots.txt 存在（{{bytes}} 字节）",
                "sitemap_ref_present": "robots.txt 中引用了 sitemap",
                "sitemap_ref_missing": "robots.txt 中没有引用 sitemap",
                "wildcard_blocks_all": "通配符 user-agent 阻止了所有爬虫（Disallow: /）",
                "bots_blocked": "以下 AI 爬虫被显式屏蔽：{{bots}}",
                "bots_with_directives": "有显式规则（未屏蔽）的 AI 爬虫：{{bots}}",
                "bots_inherit_wildcard": "未显式列出（继承通配符规则）的 AI 爬虫：{{bots}}",
                "ai_txt_found": "找到 {{path}} — 已声明 AI 爬虫策略",
                "ai_txt_not_found": "未找到 ai.txt 或 .well-known/ai.txt — 这是一项新兴的 AI 专属策略标准"
              },
              "llms": {
                "found": "找到 {{filename}}（{{lines}} 行，{{bytes}} 字节）",
                "title_present": "标题：{{title}}",
                "title_missing": "没有 Markdown 标题（# 标题）——llms.txt 规范推荐写一个",
                "description_present": "包含描述性文字",
                "description_missing": "没有描述性文字——应该说明站点或组织做什么",
                "sections_found": "找到 {{count}} 个章节（## 二级标题）",
                "sections_missing": "没有章节（## 二级标题）——建议把内容按章节组织",
                "links_found": "找到 {{count}} 个指向资源的链接",
                "links_missing": "没找到链接——llms.txt 应该链接到关键资源",
                "blockquotes_present": "包含 blockquote 描述（>）",
                "too_short": "文件非常短（{{bytes}} 字节）——可能只是占位符",
                "file_not_found": "找不到 {{filename}}"
              },
              "well_known": {
                "file_found": "找到 {{path}} —— {{description}}",
                "invalid_json": "{{path}} 存在但 JSON 语法无效",
                "file_not_found": "找不到 {{path}} —— {{description}}"
              },
              "sitemap": {
                "found": "在 {{path}} 找到 sitemap（{{count}} 条 <loc>）",
                "lastmod_present": "sitemap 带 <lastmod> 时间戳",
                "lastmod_missing": "sitemap 缺少 <lastmod> 时间戳——有助于 AI 引擎判断内容新鲜度",
                "not_found": "没有找到 sitemap.xml"
              },
              "meta": {
                "fetch_failed": "无法抓取首页",
                "title_found": "找到 <title>：\"{{title}}\"",
                "title_missing": "缺少 <title> 标签",
                "description_found": "找到 meta description（{{chars}} 字符）",
                "description_too_short": "meta description 太短——建议 120–160 字符",
                "description_missing": "缺少 meta description",
                "canonical_found": "已设置 canonical URL：{{url}}",
                "canonical_missing": "没有 canonical URL——会让 AI 引擎产生重复内容问题",
                "og_tags_found": "找到 Open Graph 标签：{{tags}}",
                "og_tags_missing": "没有 Open Graph 标签——AI 引擎用它生成内容摘要",
                "lang_declared": "已声明语言：{{lang}}",
                "lang_missing": "<html> 没有 lang 属性——有助于 AI 引擎判断内容语言",
                "hreflang_found": "找到 hreflang 标签：{{langs}}",
                "hreflang_missing": "没有 hreflang 标签——如果是多语言站点请补上",
                "twitter_cards_found": "找到 Twitter Card 标签：{{tags}}",
                "twitter_cards_missing": "缺少 Twitter Card 标签：{{missing}} — 有助于改善 X/Twitter 链接预览"
              },
              "mobile": {
                "fetch_failed": "无法抓取首页",
                "viewport_found": "找到 viewport meta 标签：{{viewport}}",
                "viewport_responsive": "使用了 width=device-width（响应式）",
                "viewport_not_responsive": "viewport 没有使用 width=device-width",
                "viewport_missing": "缺少 viewport meta 标签——页面在移动端无法正常渲染",
                "weight_light": "HTML 页面大小：{{kb}} KB（轻量）",
                "weight_medium": "HTML 页面大小：{{kb}} KB——建议减少内联 CSS/JS",
                "weight_heavy": "HTML 页面大小：{{kb}} KB——过重，可能拖慢 AI 爬虫",
                "inline_heavy": "内联资源过多：{{styles}} 个 <style> 块、{{scripts}} 个大型 <script> 块",
                "inline_ok": "内联资源在可接受范围",
                "cache_headers_found": "找到缓存头：{{signals}}",
                "cache_headers_missing": "没有缓存头（Cache-Control、ETag、Last-Modified）"
              },
              "structured_data": {
                "fetch_failed": "无法抓取首页",
                "jsonld_found": "找到 {{count}} 个 JSON-LD 结构化数据块",
                "jsonld_missing": "没有 JSON-LD 结构化数据——有助于 AI 引擎理解你的内容",
                "schema_ref_only": "找到 schema.org 引用（可能是 microdata 或 RDFa）",
                "granular_types": "存在精细化 schema 类型：{{types}}",
                "generic_only": "仅有通用 schema 类型（{{types}}）——建议添加更精细的类型以便 AI 引擎提取更多信息",
                "nonstandard_types": "检测到非标准 @type——建议使用 schema.org 精细化类型",
                "product_reviews": "Product schema 包含评论/评分——强 AI 信号",
                "product_no_reviews": "Product schema 存在但缺少 review/aggregateRating 字段"
              },
              "content_access": {
                "fetch_failed": "无法抓取首页",
                "words_ok": "首页初始 HTML 中含 {{count}} 个词",
                "words_low": "首页初始 HTML 只有 {{count}} 个词——可能过度依赖 JavaScript 渲染",
                "words_js_only": "首页只有 {{count}} 个词——可能是纯 JS 渲染，对大多数 AI 爬虫不可见",
                "ratio_good": "内容/HTML 比例：{{ratio}}%（良好）",
                "ratio_low": "内容/HTML 比例：{{ratio}}%——占位符/样板代码太多，真实内容太少",
                "ratio_very_low": "内容/HTML 比例：{{ratio}}%——极低，几乎全是样板代码",
                "headings_found": "找到标题层级（{{summary}}）",
                "first_heading_not_h1": "第一个标题是 <{{tag}}>，不是 <h1>——清晰的层级有助于 AI 引擎",
                "headings_missing": "没有标题标签——结构化标题有助于 AI 引擎解析内容"
              },
              "crawl_ready": {
                "fetch_failed": "无法抓取首页",
                "spa_empty": "疑似纯客户端渲染 SPA，几乎没有服务端内容",
                "spa_with_ssr": "检测到 SPA 框架但包含服务端内容（SSR/SSG）",
                "ssr_content": "内容由服务端渲染",
                "meta_noindex": "meta robots 包含 noindex——本页面将被排除在 AI 训练数据之外",
                "meta_nofollow": "meta robots 包含 nofollow——AI 爬虫不会跟随本页链接",
                "meta_noai": "meta robots 包含 AI 退出指令：{{content}}",
                "meta_allows_index": "meta robots 允许索引：{{content}}",
                "meta_no_restriction": "没有限制性 meta robots 标签",
                "xrobots_restrict": "X-Robots-Tag header 限制 AI：{{header}}",
                "xrobots_present": "存在 X-Robots-Tag header：{{header}}",
                "xrobots_clean": "没有限制性 X-Robots-Tag header",
                "paywall_detected": "检测到可能的付费墙（class/id：{{classes}}）",
                "no_paywall": "未检测到付费墙或登录墙",
                "semantic_good": "良好的语义 HTML 结构（{{tags}}）",
                "semantic_limited": "语义 HTML 使用有限（{{tags}}）——更多语义标签有助于 AI 解析",
                "semantic_missing": "没有语义 HTML 标签——AI 爬虫依赖语义结构",
                "alt_good": "{{with_alt}}/{{total}} 张图片有 alt 文本（{{pct}}%）",
                "alt_medium": "{{with_alt}}/{{total}} 张图片有 alt 文本（{{pct}}%）——目标 >80%",
                "alt_poor": "只有 {{with_alt}}/{{total}} 张图片有 alt 文本（{{pct}}%）——AI 爬虫需要 alt",
                "no_images": "首页没有图片",
                "internal_links_good": "{{count}} 个内链——有利于 AI 爬虫发现",
                "internal_links_few": "只有 {{count}} 个内链——更多内链有助于 AI 引擎发现内容",
                "internal_links_none": "内链极少（{{count}}）——AI 爬虫依赖链接发现内容",
                "response_fast": "响应时间：{{seconds}}s",
                "response_slow": "响应时间：{{seconds}}s——响应慢会让 AI 爬虫跳过页面",
                "response_timeout": "响应时间：{{seconds}}s——对可靠爬取而言太慢"
              },
              "content_quality": {
                "fetch_failed": "无法抓取首页",
                "readability_good": "可读性：Flesch-Kincaid 等级 {{grade}}（易读）",
                "readability_simple": "可读性：Flesch-Kincaid 等级 {{grade}}（非常简单）",
                "readability_complex": "可读性：Flesch-Kincaid 等级 {{grade}}（复杂）——更简单的文本在 AI 答案中排名更好",
                "faq_detected": "检测到 FAQ 内容——对 AI 生成答案是强信号",
                "faq_partial": "疑似 FAQ 内容——建议添加 FAQPage 结构化数据",
                "faq_missing": "未检测到 FAQ 内容——FAQ 页面在 AI 答案中排名很好",
                "stats_good": "找到 {{count}} 条可引用的统计数据——有利于 AI 引用",
                "stats_few": "找到 {{count}} 条统计数据——更多具体数据会提升被 AI 引用的可能性",
                "stats_missing": "没有可引用的统计数据——具体数字/数据有助于 AI 引用你的内容",
                "sources_cited": "找到 {{count}} 处来源引用——增加 AI 引擎的信任",
                "sources_missing": "没有明确的来源引用——引用来源会增加 AI 对内容的信任",
                "lists_good": "找到结构化列表（{{lists}} 个列表，{{items}} 项）",
                "lists_few": "列表内容较少（{{items}} 项）——结构化列表有助于 AI 提取要点",
                "lists_missing": "没有列表元素——结构化列表有助于 AI 引擎提取要点",
                "first_para_good": "首段（{{words}} 字）包含可提取的事实：{{facts}}",
                "first_para_length": "首段有事实要点（{{facts}}），但字数为 {{words}}——建议 25–120 字",
                "first_para_no_facts": "首段（{{words}} 字）缺少可提取的事实——建议在开头添加定义或关键数据",
                "first_para_missing": "无法识别实质性首段——AI 引擎依赖页面前部内容进行信息提取"
              },
              "tech_crawl": {
                "fetch_failed": "无法抓取首页",
                "canonical_chain": "检测到 canonical 链：{{from}} -> {{via}} -> {{to}}",
                "canonical_resolves": "Canonical URL 解析正确",
                "canonical_broken": "Canonical URL {{url}} 返回错误",
                "canonical_self": "Canonical URL 自引用（正确）",
                "redirect_chain": "存在 {{hops}} 跳重定向链：{{chain}} -> {{final}}",
                "redirect_ok": "{{count}} 次重定向——在可接受范围",
                "no_redirect": "没有重定向——直接访问",
                "redirect_test_failed": "无法测试重定向链",
                "http2_supported": "支持 HTTP/{{version}}——爬取更快",
                "http1_only": "HTTP/{{version}}——建议升级到 HTTP/2 或 HTTP/3 以加快爬取",
                "http_unknown": "无法确定 HTTP 版本",
                "feed_declared": "找到 RSS/Atom feed：{{feeds}}",
                "feed_found_at_path": "在 {{path}} 找到 feed",
                "feed_missing": "没有找到 RSS/Atom feed——feed 有助于 AI 引擎监控内容更新",
                "feed_full_content": "Feed 提供完整内容（平均每条 {{avg_words}} 字）——对 AI 友好",
                "feed_excerpts": "Feed 仅提供摘要（平均每条 {{avg_words}} 字）——建议输出完整内容",
                "feed_headlines_only": "Feed 条目非常短（平均 {{avg_words}} 字）——基本只有标题",
                "machine_readable": "机器可读/集成端点：{{paths}}",
                "no_machine_readable": "未检测到 API / 集成 / Webhook 文档"
              },
              "authority": {
                "fetch_failed": "无法抓取首页",
                "security_headers_strong": "安全头齐全（{{count}}/4）：{{headers}}",
                "security_headers_partial": "部分安全头（{{count}}/4）：{{headers}}",
                "security_headers_missing": "没有安全头——降低 AI 引擎的信任信号",
                "humans_txt_found": "找到 humans.txt——展示作者身份",
                "humans_txt_missing": "没有 humans.txt——可选的作者身份声明文件",
                "author_jsonld": "结构化数据（JSON-LD）中有作者信息",
                "author_meta": "meta/link 标签中有作者信息",
                "author_class_only": "HTML 中检测到 author class——建议添加 schema.org Person 标记",
                "author_missing": "没有作者署名——作者信号会提升 AI 信任度（E-E-A-T）",
                "bio_page_found": "在 {{path}} 找到个人介绍/关于页面",
                "credentials_found": "个人介绍中的资质信号：{{credentials}}",
                "credentials_weak": "个人介绍页缺少资质描述——建议补充学历、经验等信息",
                "external_bylines": "外部署名/资料链接：{{bylines}}",
                "no_external_bylines": "个人介绍页未检测到外部署名链接",
                "no_bio_page": "未找到作者介绍 / 关于我们 / 团队页面"
              },
              "ai_opt": {
                "fetch_failed": "无法抓取首页",
                "freshness_found": "找到内容新鲜度信号：",
                "freshness_missing": "没有内容新鲜度信号——在 JSON-LD 里加 dateModified 或用 <time> 元素",
                "brand_inconsistent": "各标签中站点名不一致：{{names}}",
                "brand_consistent": "品牌实体「{{name}}」使用一致（{{count}} 次）",
                "brand_sparse": "品牌实体「{{name}}」存在但使用偏少——一致命名有助于 AI 实体识别",
                "brand_unknown": "无法确定主要品牌/实体名称",
                "api_endpoint_found": "找到机器可读端点：{{path}}",
                "api_endpoint_missing": "没有公开 API 端点——可选，但有助于 AI 系统访问结构化数据",
                "sitemap_cadence": "Sitemap 含 {{total}} 条 <lastmod>（中位更新天数：{{median_days}} 天，{{fresh_90}}/{{count}} 在过去 90 天内更新）",
                "cadence_healthy": "全站更新节奏健康",
                "cadence_moderate": "更新节奏中等——不到一半页面在过去 90 天内更新",
                "cadence_low": "更新节奏偏低——大多数页面已过时（中位 {{median_days}} 天）",
                "cadence_unknown": "无法分析全站更新节奏（sitemap 中没有可解析的 <lastmod>）"
              },
              "social": {
                "fetch_failed": "无法抓取首页",
                "twitter_found": "找到 Twitter/X card 标签：{{tags}}",
                "twitter_missing": "没有 Twitter/X card meta 标签",
                "sameas_found": "JSON-LD 中有 {{count}} 条 sameAs 社交链接：",
                "sameas_missing": "结构化数据中没有 sameAs 社交档案链接",
                "html_links_found": "HTML 中找到 {{count}} 个社交档案链接——建议同时加到 JSON-LD 的 sameAs",
                "no_social_links": "页面上没有检测到社交档案链接"
              },
              "answer_format": {
                "fetch_failed": "无法抓取首页",
                "definitions_found": "找到 {{count}} 句定义式表述——对 AI 引用非常友好",
                "definitions_missing": "没有检测到定义式表述",
                "tables_with_headers": "找到带 header 的对比表格——AI 引擎会提取表格数据",
                "tables_without_headers": "找到表格但缺少 <th> header——加上 header 方便 AI 提取",
                "tables_missing": "没有对比表格——建议为功能对比、定价等场景添加",
                "steps_found": "检测到分步指南内容——对「how to」类 AI 答案非常有利",
                "steps_missing": "没有找到分步指南",
                "proscons_found": "检测到优劣 / pros-cons 内容",
                "proscons_missing": "没有检测到优劣结构",
                "summary_found": "找到摘要/关键要点区块——AI 引擎偏好简明摘要",
                "summary_missing": "没有关键要点或 TL;DR 区块",
                "question_headings_strong": "{{count}} 个问句式标题——对话式搜索就绪度高",
                "question_headings_few": "仅 {{count}} 个问句式标题——建议增加更多以匹配对话式查询",
                "question_headings_none": "未检测到问句式标题——对话式搜索就绪度低"
              },
              "platform_reg": {
                "fetch_failed": "无法抓取首页",
                "gsc_verified": "找到 Google Search Console 验证标签",
                "gsc_missing": "没有 Google Search Console 验证标签",
                "bing_verified": "找到 Bing Webmaster Tools 验证标签",
                "bing_missing": "没有 Bing Webmaster Tools 验证标签",
                "yandex_verified": "找到 Yandex Webmaster 验证标签",
                "yandex_missing": "没有 Yandex Webmaster 验证标签——如面向国际 AI 平台可补充",
                "indexnow_endpoint": "在 {{path}} 找到 IndexNow 端点——可即时通知索引更新",
                "indexnow_meta": "找到 IndexNow meta 标签",
                "indexnow_missing": "未检测到 IndexNow 集成",
                "pinterest_verified": "找到 Pinterest 域名验证",
                "summary_registered": "已注册：{{platforms}}",
                "summary_missing": "未检测到：{{platforms}}"
              },
              "schema_kg": {
                "fetch_failed": "无法抓取首页",
                "breadcrumb_schema": "找到 BreadcrumbList 结构化数据——有助于 AI 理解站点层级",
                "breadcrumb_html_only": "HTML 中有面包屑但缺少 BreadcrumbList 结构化数据",
                "breadcrumb_none": "没有面包屑导航或相应结构化数据",
                "org_schema_found": "找到 Organization/Business 结构化数据：@type = {{type}}",
                "org_field_present": "{{label}}：存在",
                "org_field_missing": "{{label}}：缺失",
                "optional_present": "可选字段已填：{{fields}}",
                "optional_missing": "可选字段缺失：{{fields}}",
                "org_schema_missing": "没有 Organization/LocalBusiness 结构化数据——知识面板需要它"
              },
              "url_norm": {
                "host_redirects": "{{alt}} 重定向到 {{main}}（一致）",
                "host_duplicate": "{{main}} 和 {{alt}} 都提供内容——存在重复内容风险",
                "host_alt_inaccessible": "备用主机名（{{alt}}）不可访问",
                "slash_both_200": "末尾带/不带斜杠都返回 200——请确保设置了 canonical",
                "slash_redirect": "末尾斜杠一致性通过重定向处理",
                "path_consistent": "URL 路径一致",
                "case_mixed": "大小写 URL 解析到不同页面——可能造成重复内容",
                "case_consistent": "URL 大小写处理一致"
              },
              "outbound": {
                "fetch_failed": "无法抓取首页",
                "links_found": "找到 {{count}} 条出站链接，覆盖 {{domains}} 个唯一域名",
                "authoritative_links": "链接到权威来源：{{domains}}",
                "no_authoritative": "未检测到 .gov/.edu/.org 权威来源链接",
                "no_outbound_links": "没有出站链接——链接到权威来源能提升内容可信度",
                "video_schema_found": "找到 VideoObject 结构化数据",
                "video_no_schema": "找到视频内容（{{count}} 个嵌入）但没有 VideoObject 结构化数据",
                "no_video": "未检测到视频内容",
                "transcript_found": "找到视频转写内容——AI 引擎可以索引转写文本",
                "transcript_missing": "找到视频但未检测到转写内容",
                "tables_well_formed": "找到 {{count}} 个表格，都有合规的 <thead>/<th> 标记",
                "tables_partial_headers": "{{well_formed}}/{{total}} 个表格有合规的 header——其余需补齐",
                "tables_no_headers": "找到 {{count}} 个表格但都缺少 <thead>/<th> header",
                "no_tables": "首页没有表格",
                "definition_markup": "找到定义标记：{{dfn}} 个 <dfn>、{{abbr}} 个 <abbr>",
                "no_definition_markup": "没有 <dfn> 或 <abbr>——建议用它们标记技术术语和缩写",
                "multi_format_coverage": "多格式覆盖：{{formats}}",
                "multi_format_strong": "{{count}} 种内容格式——AI 触达面广",
                "multi_format_limited": "仅检测到 {{count}} 种非文本格式——更多格式 = 更大的 AI 触达面",
                "multi_format_none": "未检测到非文本格式——内容仅有纯文本"
              },
              "multilingual": {
                "fetch_failed": "无法抓取首页",
                "no_hreflang": "没有 hreflang 标签——跳过多语言检查",
                "lang_substantive": "[{{lang}}] 包含充实内容（{{count}} 字）",
                "lang_thin": "[{{lang}}] 内容非常稀薄（{{count}} 字）：{{url}}",
                "lang_broken": "[{{lang}}] 页面损坏或不可访问：{{url}}",
                "all_good": "所有备用语言页面均包含充实内容"
              },
              "cross_platform": {
                "linked_on_site": "{{platform}} 已在站点链接：{{url}}",
                "profile_found": "找到 {{platform}} 档案：{{url}}",
                "not_detected": "未检测到 {{platform}}",
                "presence_strong": "跨平台存在度强：{{found}}/{{total}} 个平台",
                "presence_moderate": "跨平台存在度中等：{{found}}/{{total}} 个平台",
                "presence_limited": "跨平台存在度有限：{{found}}/{{total}} 个平台",
                "presence_none": "未检测到跨平台存在"
              },
              "multi_page": {
                "no_internal_pages": "没有内部页面可采样",
                "no_content_pages": "没有找到可采样的内容页面",
                "missing_title": "{{count}} 个页面缺少 <title>：",
                "missing_description": "{{count}} 个页面缺少 meta description：",
                "missing_canonical": "{{count}} 个页面缺少 canonical URL：",
                "missing_structured_data": "{{count}} 个页面没有结构化数据（JSON-LD）：",
                "missing_h1": "{{count}} 个页面缺少 <h1>：",
                "low_word_count": "{{count}} 个页面字数过低（<100）：",
                "missing_og": "{{count}} 个页面缺少 Open Graph 标签：",
                "missing_alt_text": "{{count}} 个页面大多数图片缺少 alt 文本：",
                "duplicate_descriptions": "跨页面存在重复的 meta description：",
                "duplicate_titles": "跨页面存在重复的 <title> 标签：",
                "content_overlap": "页面间存在内容重叠 / 可能的关键词蚕食：",
                "all_good": "所有采样页面都保持一致的 GEO 标准"
              },
              "brand_kg": {
                "wikipedia_found": "找到 Wikipedia 页面：\"{{title}}\"",
                "wikipedia_not_found": "未找到 \"{{brand}}\" 的 Wikipedia 页面",
                "wikidata_found": "找到 Wikidata 实体：{{id}}",
                "wikidata_not_found": "未找到 \"{{brand}}\" 的 Wikidata 实体",
                "backlinks_strong": "Wikipedia 反向链接：{{count}}+ 个页面指向该实体——权威度强",
                "backlinks_moderate": "Wikipedia 反向链接：{{count}} 个页面指向该实体",
                "backlinks_weak": "仅 {{count}} 条 Wikipedia 反向链接——实体已被识别但较小众"
              },
              "trust_safety": {
                "fetch_failed": "无法抓取首页",
                "privacy_found": "找到隐私政策页面：{{path}}",
                "privacy_missing": "未检测到隐私政策页面",
                "terms_found": "找到服务条款页面：{{path}}",
                "terms_missing": "未检测到服务条款页面",
                "contact_found": "找到联系页面：{{path}}",
                "contact_missing": "未检测到联系页面",
                "legal_found": "找到法律/DMCA/印记页面：{{path}}",
                "legal_missing": "未检测到 DMCA / 法律 / 印记页面",
                "identity_strong": "页脚/结构化数据中有完善的商业身份信息：{{signals}}",
                "identity_partial": "部分商业身份信息：{{signals}}",
                "identity_missing": "未找到商业身份信号（邮箱、电话、地址或法律实体）"
              }
            },
            "fixes": {
              "ai_opt": {
                "add_brand_meta": "通过以下方式让品牌名易于被发现：\n  <meta property=\"og:site_name\" content=\"Your Brand\" />\n并在 <title> 中统一使用 'Brand — Page Title' 格式。",
                "add_freshness": "添加新鲜度信号，让 AI 引擎判断内容是否最新：\n  1. 在 JSON-LD 中加入 \"dateModified\": \"2025-01-15\"\n  2. 使用 <time> 标签：<time datetime=\"2025-01-15\">January 15, 2025</time>\n  3. 在服务器响应中设置 Last-Modified 头",
                "unify_brand_name": "在所有位置使用同一个品牌名。确保 og:site_name、<title> 后缀、\nJSON-LD Organization 中的 name 完全一致。\n请从下列名称中选定一个：{names}",
                "use_brand_consistently": "在页面内容中更稳定地使用品牌名 \"{name}\"。\n在标题、开头段落和结构化数据中提及该名称，以强化实体识别。",
                "increase_cadence": "提高内容更新频率。AI 引擎偏好定期更新的站点——\n长期不更新的页面会逐渐退出训练窗口和检索索引。",
                "refresh_stale_content": "大部分内容已数月未更新。请定期刷新高价值页面\n（更新数据、补充新案例、更新 dateModified），让 AI 引擎看到持续维护。"
              },
              "answer_format": {
                "add_comparison_tables": "在合适的位置加入对比表格（价格、功能、对标竞品）：\n  <table>\n    <thead><tr><th>Feature</th><th>Basic</th><th>Pro</th></tr></thead>\n    <tbody>...</tbody>\n  </table>\nAI 引擎在对比类回答中常常引用表格数据。",
                "add_definitions": "添加可被 AI 引擎直接引用的定义句：\n  'Generative Engine Optimization (GEO) is the practice of optimizing web content...'\n  'A sitemap refers to a file that lists all pages on a website...'\n句式：'[Term] is/are [clear definition].'",
                "add_proscons": "为产品、服务或对比内容添加优缺点段落：\n  <h3>Pros</h3>\n  <ul><li>Fast performance</li><li>Easy to use</li></ul>\n  <h3>Cons</h3>\n  <ul><li>Limited free tier</li><li>No mobile app</li></ul>\nAI 引擎在推荐类回答中常引用平衡的优缺点。",
                "add_steps": "在合适的位置加入编号步骤说明：\n  <h2>How to Set Up Your Account</h2>\n  <ol>\n    <li>Go to the signup page</li>\n    <li>Enter your email address</li>\n    <li>Verify your account</li>\n  </ol>\nAI 引擎在 'how to' 类查询中会优先呈现分步内容。",
                "add_summary": "在页面靠前或靠后位置加入 'Key Takeaways' 或 'TL;DR' 区块：\n  <h2>Key Takeaways</h2>\n  <ul>\n    <li>Main point 1</li>\n    <li>Main point 2</li>\n  </ul>\nAI 引擎在生成快速回答时常引用摘要段落。",
                "add_question_headings": "添加更多问句式标题以匹配用户向 AI 引擎提问的方式：\n  <h2>什么是 GEO？</h2>\n  <h2>如何为 AI 搜索做优化？</h2>\n  <h2>为���么 GEO 很重要？</h2>\n每个问题后紧跟简短直接的回答，便于 AI 引擎提取。",
                "add_question_headings_intro": "添加问句式标题，让 AI 引擎能将对话式查询匹配到你的内容：\n  <h2>什么是 GEO？</h2>\n  <h3>这是如何运作的？</h3>\n围绕 谁/什么/如何/为什么 组织的页面在 AI 答案中排名更高。",
                "add_table_headers": "为表格补���表头：\n  <table>\n    <thead><tr><th>Feature</th><th>Plan A</th><th>Plan B</th></tr></thead>\n    <tbody><tr><td>Price</td><td>$10</td><td>$20</td></tr></tbody>\n  </table>\nAI 引擎会从结构良好的表格中抽取对比答案。"
              },
              "authority": {
                "add_author": "添加作者信息以增强 E-E-A-T 信号：\n  1. 添加 <meta name=\"author\" content=\"Author Name\">\n  2. 或在 JSON-LD 中添加 author 字段：\n     \"author\": {\"@type\": \"Person\", \"name\": \"Author Name\"}\n  3. 博客文章应在页面可见处展示作者姓名、简介与资历。",
                "add_humans_txt": "在站点根目录创建 humans.txt 表明作者身份：\n  /* TEAM */\n  Name: Your Name\n  Role: Lead Developer\n  Contact: email@example.com\n  \n  /* SITE */\n  Last update: 2025/01/15\n  Standards: HTML5, CSS3\n完整规范见 humanstxt.org。",
                "add_security_headers": "在服务器配置中补齐安全响应头：\n  Strict-Transport-Security: max-age=31536000; includeSubDomains\n  Content-Security-Policy: default-src 'self'\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY",
                "add_security_headers_nginx": "为响应添加安全头部，Nginx 示例：\n  add_header Strict-Transport-Security \"max-age=31536000; includeSubDomains\" always;\n  add_header Content-Security-Policy \"default-src 'self'\" always;\n  add_header X-Content-Type-Options \"nosniff\" always;\n  add_header X-Frame-Options \"DENY\" always;",
                "strengthen_bio": "用显式的 E-E-A-T 信号强化个人介绍/关于页面：\n  • 学历与资质（博士、认证等）\n  • 工作年限与职位\n  • 知名前任雇主或合作方\n  • 外部署名文章、出版物或媒体报道",
                "add_external_bylines": "在个人介绍/关于页面中链接外部署名（Medium、Substack、行业媒体、Google Scholar、ORCID）。\n独立第三方署名比自我声明具有更强的 E-E-A-T 权重。",
                "create_about_page": "创建一个内容丰富的 /about 或 /team 页面（200 字以上），\n说明站点背后的团队：真实姓名、资质、照片、联系方式和外部资料链接。\nAI 引擎对匿名站点的 E-E-A-T 评分较低。",
                "upgrade_author_jsonld": "用 JSON-LD 结构化数据完善作者信息：\n  \"author\": {\n    \"@type\": \"Person\",\n    \"name\": \"Author Name\",\n    \"url\": \"https://authorsite.com\"\n  }"
              },
              "content_access": {
                "add_h1": "确保页面首个标题是包含主题的 <h1>。\n使用合理的层级：h1 > h2 > h3，不要跳级。",
                "add_headings": "用标题标签构建内容层级：\n  <h1>Main Page Topic</h1>\n  <h2>Subtopic</h2>\n  <h3>Detail</h3>\n标题层次有助于 AI 引擎理解结构并提取核心主题。",
                "client_rendered_workarounds": "页面内容可能完全依赖客户端 JavaScript 渲染，而 AI 爬虫无法执行 JS。\n可选方案：\n  1. 服务端渲染（SSR）——Next.js、Nuxt.js 等\n  2. 静态站点生成（SSG）——构建时预渲染页面\n  3. 接入预渲染服务（如 Prerender.io）为爬虫返回静态 HTML",
                "enable_ssr": "确保关键内容由服务端渲染（SSR/SSG），便于 AI 爬虫读取。\n若使用 React/Vue/Angular，可改用 Next.js/Nuxt.js/Angular Universal 启用服务端渲染。",
                "improve_text_ratio": "正文占比过低，常见原因：\n  1. 大量行内 CSS/JS 框架——拆分到外部文件\n  2. 完全使用客户端渲染——改用 SSR/SSG\n  3. 内容隐藏在 JavaScript 状态中——确保 HTML 中包含可读文本",
                "reduce_html_bloat": "精简 HTML：减少行内 CSS/JS、移除冗余标记、将脚本拆分到外部文件。\n确保 body 中含有具有实质价值的独特内容，而不只是导航和页脚。"
              },
              "content_quality": {
                "add_attributions": "添加来源标注以增强可信度：\n  'According to [Source Name], ...'\n  'Data from our 2025 industry report shows...'\n  'A study by [Institution] found...'\nAI 引擎对带来源的论述给予更高权重。",
                "add_faq_schema": "添加 FAQPage 结构化数据以提升 AI 答案排名：\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"FAQPage\",\n    \"mainEntity\": [{\n      \"@type\": \"Question\",\n      \"name\": \"What is your product?\",\n      \"acceptedAnswer\": {\n        \"@type\": \"Answer\",\n        \"text\": \"Our product is...\"\n      }\n    }]\n  }\n  </script>",
                "add_faq_section": "建议为页面添加 FAQ 区块，问题用标题表示：\n  <h2>Frequently Asked Questions</h2>\n  <h3>What does your product do?</h3>\n  <p>Clear, concise answer...</p>\n再为每个问答对补充 FAQPage JSON-LD 结构化数据。",
                "add_lists": "使用结构化列表，便于 AI 提取关键信息：\n  <ul>\n    <li>Key feature or benefit</li>\n    <li>Another important point</li>\n  </ul>\n步骤/流程使用 <ol>，特性/优势使用 <ul>。",
                "add_statistics": "在内容中加入可被引用的具体数据：\n  '95% of customers report improved performance'\n  'Over 10,000 companies use our platform'\n  'Reduces processing time by 3.5x'\nAI 引擎更倾向于引用具体数据而不是模糊表述。",
                "tighten_first_para": "将开头段落精炼至 25–120 字，便于 AI 引擎将其作为摘要直接引用。",
                "frontload_facts": "在首段前置事实，便于 AI 引擎直接提取：\n  '生成式引擎优化（GEO）是为 AI 搜索引擎优化网页内容的实践。\n   超过 70% 的搜索用户在点击链接之前会先咨询 AI 助手。'\n目标：首段 25–120 字内至少包含一句定义和一条具体数据。",
                "add_opening_para": "在页面主体（<main> 或 <article>）的靠前位置放置一个实质性的开头段落，\n用定义和/或具体数字回答「这个页面关于什么？」。",
                "simplify": "简化内容，提高 AI 可读性：\n  1. 使用更短的句子（20 个单词以内）\n  2. 用通俗表达替代专业术语\n  3. 将复杂概念拆分为列表条目\n  4. 优先使用主动语态\n  5. 控制在 8–10 年级阅读水平"
              },
              "crawl_ready": {
                "add_alt_text": "为所有 <img> 标签补充描述性 alt 文本：\n  <img src=\"photo.jpg\" alt=\"Description of what the image shows\" />\n好的 alt 应当具体，例如 'Team meeting in conference room' 而不是 'image1'。",
                "add_alt_text_majority": "大多数图片缺少 alt 文本。请为每个 <img> 添加描述性 alt：\n  <img src=\"photo.jpg\" alt=\"Descriptive text about the image content\" />\n纯装饰性图片可使用 alt=\"\"（保留属性但留空）。",
                "add_internal_links": "增加内部链接，帮助 AI 爬虫发现更多内容。\n在导航、页脚以及正文中加入指向关键页面的链接。\n使用具有描述性的锚文本，例如 'Read our pricing guide' 而不是 'click here'。",
                "add_internal_links_homepage": "首页内部链接过少，AI 爬虫依赖链接发现页面。建议添加：\n  1. 指向核心栏目的导航菜单\n  2. 正文中的精选内容链接\n  3. 包含重要页面链接的页脚\n  4. 正文内的上下文链接",
                "add_semantic_html5": "用语义化 HTML5 标签替换通用 <div>：\n  <header>：页头/导航\n  <main>：主体内容\n  <article>：独立成篇的内容\n  <section>：主题分组\n  <aside>：侧栏/相关内容\n  <footer>：页脚",
                "critical_response_time": "响应时间极慢，AI 爬虫可能超时。立即处理：\n  1. 在源站前部署 CDN\n  2. 在服务器层启用页面缓存\n  3. 对服务端代码做性能剖析定位瓶颈\n  4. 内容页面可考虑改为静态生成",
                "enable_ssr": "在前端框架中启用服务端渲染：\n  Next.js：使用 getServerSideProps() 或 generateStaticParams()\n  Nuxt.js：在 nuxt.config 中设置 ssr: true\n  纯 React：建议迁移到 Next.js 或 Remix",
                "improve_response_time": "优化响应时间：\n  1. 启用服务端缓存（Redis、Varnish、CDN）\n  2. 优化数据库查询\n  3. 使用 CDN（Cloudflare、Fastly、CloudFront）\n  4. 开启 gzip/brotli 压缩",
                "paywall_workarounds": "AI 爬虫无法访问付费墙/登录墙后的内容。\n可考虑：\n  1. 在收费墙之前提供充分的免费预览或摘要\n  2. 采用计次访问，让爬虫首次访问时能看到全文\n  3. 在墙外提供包含核心事实的 JSON-LD 结构化数据",
                "remove_noai": "'noai' / 'noimageai' 指令会让你的内容退出 AI 训练。\n如希望 AI 引擎在回答中引用你的内容，请将其移除。",
                "remove_nofollow": "若希望 AI 爬虫发现页面中的链接，请移除 'nofollow'：\n  <meta name=\"robots\" content=\"index, follow\" />",
                "remove_noindex": "若希望 AI 引擎索引该页面，请从 meta robots 中移除 'noindex'：\n  <meta name=\"robots\" content=\"index, follow\" />",
                "remove_xrobots": "在服务器配置中移除限制性的 X-Robots-Tag 响应头。\nNginx：删除 'add_header X-Robots-Tag \"noindex\";'\nApache：删除 'Header set X-Robots-Tag \"noindex\"'",
                "replace_divs": "页面仅使用 <div> 标签。请替换为语义化 HTML5 元素：\n  <header>、<nav>、<main>、<article>、<section>、<aside>、<footer>\n这能帮助 AI 引擎理解每个内容块的角色。"
              },
              "cross_platform": {
                "expand_presence": "在 AI 模型的训练数据来源平台上扩展品牌存在：{platforms}\nAI 引擎（ChatGPT、Perplexity、Claude、Gemini）会从这些平台获取训练数据。\n在更多平台上出现可以提高品牌被 AI 回答引用的概率，\n无论 AI 实际引用的是哪一个来源。"
              },
              "https": {
                "enable_https": "为站点安装 SSL/TLS 证书（可通过 Let's Encrypt 免费获取），并将全部 HTTP 流量 301 重定向到 HTTPS。\nNginx 示例：return 301 https://$host$request_uri;"
              },
              "llms": {
                "add_description": "在标题下方添加一段说明，介绍站点或组织的业务：\n  # Your Site\n  A brief description of your site and what it offers.",
                "add_links": "在 llms.txt 中以 markdown 链接列出关键页面：\n  - [Documentation](https://yoursite.com/docs)\n  - [API Reference](https://yoursite.com/api)",
                "add_sections": "用分节组织 llms.txt 内容，例如：\n  ## Documentation\n  ## API Reference\n  ## Blog",
                "add_title": "将标题作为 {filename} 的第一行：\n  # Your Site Name",
                "create_file": "在站点根目录创建 llms.txt 文件，结构示例：\n  # Your Site Name\n  A brief description of your site.\n  \n  ## Documentation\n  > Overview of your docs\n  - [Getting Started](https://yoursite.com/docs/start)\n  \n  ## API\n  > API reference\n  - [API Docs](https://yoursite.com/api)",
                "create_full_file": "创建 llms-full.txt 提供扩展内容——它是 llms.txt 的详细版本，\n包含完整说明、完整资源清单以及为 AI 模型准备的更深层上下文。",
                "expand_content": "扩充 llms.txt 的内容，加入站点定位、核心页面与重要资源等有实际价值的信息。"
              },
              "meta": {
                "add_canonical": "在 <head> 中添加 canonical 链接：\n  <link rel=\"canonical\" href=\"https://yoursite.com/current-page\" />\n以告知 AI 引擎哪一个版本的页面才是权威版本。",
                "add_description": "在 <head> 中添加 meta description：\n  <meta name=\"description\" content=\"A 120-160 character summary of your page content, including key topics and value proposition.\">\nAI 引擎在概括站点时通常会引用这段描述。",
                "add_hreflang": "多语言站点请添加 hreflang 标签：\n  <link rel=\"alternate\" hreflang=\"en\" href=\"https://yoursite.com/en/page\" />\n  <link rel=\"alternate\" hreflang=\"zh\" href=\"https://yoursite.com/zh/page\" />\n  <link rel=\"alternate\" hreflang=\"x-default\" href=\"https://yoursite.com/page\" />",
                "add_lang": "为 <html> 标签添加 lang 属性：\n  <html lang=\"en\">",
                "add_og": "在 <head> 中添加 Open Graph meta 标签：\n  <meta property=\"og:title\" content=\"Page Title\" />\n  <meta property=\"og:description\" content=\"Page description\" />\n  <meta property=\"og:type\" content=\"website\" />\n  <meta property=\"og:url\" content=\"https://yoursite.com/page\" />\n  <meta property=\"og:image\" content=\"https://yoursite.com/image.jpg\" />",
                "add_title": "在 <head> 中添加 <title> 标签：\n  <title>Your Page Title — Your Brand</title>\n建议控制在 60 字符内，并包含主要关键词。",
                "expand_description": "将 meta description 扩展至 120–160 字符，包含明确的价值主张和主要关键词。",
                "add_twitter_cards": "在 <head> 中添加 Twitter Card meta 标签：\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />"
              },
              "mobile": {
                "add_cache_headers": "添加缓存响应头以提升重复抓取效率：\n  Cache-Control: public, max-age=3600\n  ETag:（多数服务器会自动生成）\n这能让 AI 爬虫使用条件请求（If-None-Match），\n避免重复下载未变更页面。",
                "add_viewport": "在 <head> 中添加 viewport meta：\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n移动优先索引意味着 AI 爬虫期望页面对移动端友好。",
                "externalize_inline": "将行内样式与脚本拆分到外部文件，减小 HTML 体积，\n并提升重复抓取时的缓存效率。",
                "reduce_weight": "减小页面体积：\n  1. 将行内 CSS 拆分到外部样式表\n  2. 将行内 JS 拆分到外部脚本并使用 defer/async\n  3. 移除无用 HTML 与注释\n  4. 在服务器开启 gzip/brotli 压缩",
                "reduce_weight_critical": "页面过大，影响抓取效率。建议：\n  1. 将所有行内 CSS 与 JS 拆分到外部文件\n  2. 移除行内 SVG 与 base64 图片，改用外部文件\n  3. 在服务器开启 gzip/brotli 压缩\n  4. JS 较重的页面考虑代码分包",
                "set_viewport_responsive": "将 viewport 设置为响应式：\n  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
              },
              "multi_page": {
                "boost_google_authority": "提升 Google 权威度：\n  - 完整填写 Organization 结构化数据（全部 9 个字段）\n  - 为品牌/产品创建 Wikipedia 词条\n  - 创建 Wikidata 实体并通过 sameAs 关联\n  - 认领 Google Business Profile\n  - 从权威域名获取高质量反向链接",
                "common_crawl_inbound_links": "Common Crawl 尚未抓取你的站点。\n对新站或小站这是正常现象。可通过获取更多反向链接来提升被发现的概率。",
                "duplicate_descriptions": "为每个页面撰写独立的 meta description。重复的描述会让\nAI 引擎在引用时无法判断哪一个页面与主题更相关。",
                "duplicate_titles": "为每个页面撰写独立的 <title>。重复的标题会导致关键词蚕食——\nAI 引擎无法判断对于给定查询应该引用哪个页面。",
                "content_overlap": "两个或多个页面覆盖高度重叠的主题。\n可选方案：\n  1. 合并为一个权威页面，其余页面 301 重定向。\n  2. 为每个页面赋予不同角度、示例和关键词加以区分。\n  3. 使用 rel=canonical 将近似重复页指向主页面。\n关键词蚕食会削弱 AI 可见性——选出最强的那个页面来展示。",
                "increase_platform_presence": "扩大在权威平台上的存在感：\n  - 创建公司 Crunchbase 资料\n  - 维护活跃的 GitHub 组织\n  - 如适用，向 npm/PyPI 发布开源包\n  - 在 Hacker News 上发布 Show HN 帖\n  - 提交到创业公司目录（Product Hunt、AngelList/Wellfound）\n  - 争取出现在行业媒体和对比类文章中",
                "list_review_platforms": "在评测平台上架产品以累积信任信号：\n  - Trustpilot（https://business.trustpilot.com）——通用评测\n  - G2（https://sell.g2.com）——B2B/SaaS 评测\n  - Product Hunt（https://producthunt.com）——发布与曝光\n  - Capterra（https://capterra.com）——软件评测\n再为站点添加 AggregateRating 结构化数据，以便在搜索结果中展示星级。",
                "low_word_count": "正文不足 100 字的页面内容过少，无法满足 AI 引擎需求。请补充实质性、独特的文本。",
                "missing_alt_text": "为这些页面上的所有图片补充描述性 alt 文本。",
                "missing_canonical": "为每个页面添加指向优选 URL 的 <link rel=\"canonical\" href=\"...\">。",
                "missing_description": "为每个页面添加唯一的 meta description（120–160 字符）概括页面内容。",
                "missing_h1": "为每个页面添加唯一的 <h1> 标签，概括页面的主要主题。",
                "missing_og": "为每个页面添加 Open Graph 标签（og:title、og:description、og:image）。",
                "missing_structured_data": "为内容页面添加 JSON-LD 结构化数据（Article、Product、FAQPage 等）。",
                "missing_title": "为每个页面添加唯一、具有描述性的 <title> 标签（不超过 60 字符）。",
                "register_search_engines": "在 Google Search Console 和 Bing Webmaster Tools 注册以获得索引。\n在两个平台分别提交 sitemap.xml。\n确保 robots.txt 没有屏蔽 AI 爬虫。\n检查 CDN/WAF 设置——部分服务默认会拦截 bot 流量。",
                "strengthen_trust": "强化信任信号：\n  - 在显眼位置展示认证（SOC2、GDPR、ISO、PCI-DSS）\n  - 为奖项徽章添加 alt 文本：<img alt='2025 Best Fintech Award' ...>\n  - 展示合作伙伴/隶属机构 Logo（Y Combinator、加速器、行业组织）\n  - 在结构化数据中标注奖项：\n    {\"@type\": \"Organization\", \"award\": [\"Best Fintech 2025\", ...]}",
                "unblock_core_bots": "这些是核心 AI 爬虫。若被屏蔽，你的内容可能无法出现在对应 AI 产品中。\n请确认已在对应搜索平台完成注册。\n检查 robots.txt 没有屏蔽这些 user agent。\n在 Google Search Console 和 Bing Webmaster Tools 提交 sitemap。",
                "unblock_robots_bots": "以下 bot 被 robots.txt 屏蔽：{bots}\n如希望 AI 引擎索引你的内容，请移除或修改对应规则：\n  User-agent: BotName\n  Disallow: /\n将 'Disallow: /' 改为 'Allow: /' 或直接移除该规则。",
                "unblock_waf_bots": "部分 AI bot 被你的服务器、CDN 或 WAF 拦截。\n检查 Cloudflare/AWS WAF/Nginx 规则，将这些 user agent 加入白名单。\n常见原因：\n  - Cloudflare Bot Fight Mode 拦截非浏览器 user agent\n  - 限速规则过于激进\n  - 安全插件（Wordfence、Sucuri）启用了严格的 bot 拦截"
              },
              "multilingual": {
                "expand_alt_pages": "其它语言页面内容过少。请确保翻译完整，而不是占位或机器翻译片段；\nAI 引擎可能会跳过内容过薄的多语言页面。",
                "fix_hreflang": "修复失效的 hreflang URL——它们当前返回错误。要么创建对应页面，\n要么移除 hreflang 标签，避免误导 AI 爬虫。"
              },
              "brand_kg": {
                "create_wikipedia": "Wikipedia 页面是 AI 引擎最强的实体信号之一。如果你的品牌具有足够知名度，\n请争取在新闻/行业媒体获得独立报道，然后按照 Wikipedia 的关注度指南提交。\n切勿自行编写——会被标记为利益冲突。",
                "create_wikidata": "Wikidata 可免费编辑，AI 引擎（尤其是 Google 知识图谱）会大量引用。\n在 https://www.wikidata.org/wiki/Special:NewItem 创建条目，填写：\n  • 标签 + 描述\n  • instance of (P31) — 如 'business'\n  • official website (P856) — 你的域名\n  • sameAs 链接到社交资料"
              },
              "trust_safety": {
                "add_privacy": "在 /privacy（或 /privacy-policy）发布隐私政策。AI 引擎将缺少隐私政策\n视为信任红旗——GDPR、CCPA 和大多数广告网络均要求提供。",
                "add_terms": "在 /terms 发布服务条款。这是 AI 引擎和搜索平台\n对正规站点的基本信任要求。",
                "add_contact": "添加 /contact 页面，至少包含邮箱地址和/或表单。AI 引擎\n在信任敏感查询中对有明确联系方式的站点给予更高排名。",
                "add_legal": "添加 /dmca 或 /legal 页面。在欧盟 'Impressum'（印记）是法律要求；\n其他地区 DMCA 代理页面可保护你免受版权侵权责任，同时提升信任度。",
                "add_identity_signals": "补充缺失的信任信号，让 AI 引擎能验证站点运营者身份。",
                "add_business_identity": "AI 引擎无法验证谁在运营此站点。请在页脚和/或 Organization JSON-LD 中添加：\n  • 实际地址（schema.org PostalAddress）\n  • 联系邮箱和电话（contactPoint）\n  • 法律实体后缀（LLC / Inc / Ltd / GmbH）及注册号（如适用）"
              },
              "outbound": {
                "add_authoritative_links": "在合适位置链接权威外部资源（学术论文、.gov/.edu 站点、行业标准）。\n指向权威来源的外链会向 AI 引擎传递「内容研究充分」的信号。",
                "add_dfn_abbr": "为关键术语与缩写添加语义标记：\n  <dfn>Generative Engine Optimization</dfn> (GEO) is...\n  <abbr title=\"Generative Engine Optimization\">GEO</abbr>\n这能帮助 AI 引擎理解并定义内容中的术语。",
                "add_outbound_links": "添加指向权威来源的外链以支撑你的论述。\nAI 引擎会将这视为内容经过充分研究、值得信赖的信号。",
                "add_table_headers_semantic": "为表格添加语义化表头，便于 AI 提取：\n  <table>\n    <thead><tr><th>Header 1</th><th>Header 2</th></tr></thead>\n    <tbody>...</tbody>\n  </table>",
                "add_table_thead": "为所有数据表格添加 <thead> 与 <th>：\n  <table>\n    <thead><tr><th>Column 1</th><th>Column 2</th></tr></thead>\n    <tbody><tr><td>Data</td><td>Data</td></tr></tbody>\n  </table>",
                "add_video_schema": "为视频内容添加 VideoObject 结构化数据：\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"VideoObject\",\n    \"name\": \"Video Title\",\n    \"description\": \"Video description\",\n    \"thumbnailUrl\": \"https://yoursite.com/thumb.jpg\",\n    \"uploadDate\": \"2025-01-15\",\n    \"contentUrl\": \"https://yoursite.com/video.mp4\"\n  }\n  </script>",
                "add_video_transcripts": "为视频内容添加文字转录，便于 AI 爬虫索引语音内容。\n将转录文本放在视频下方可见区域。",
                "diversify_formats": "丰富内容格式，让 AI 引擎在更多场景接触到你的品牌：\n  • 播客（音频转���可被 ChatGPT、Perplexity 索引）\n  • PDF 白皮书（可被引用的文档）\n  • 信息图（配合描述�� alt 文本）\n  • SlideShare / Speaker Deck 上的演示文稿\n  • 配有转写的视频",
                "add_alt_format": "至少添加一种替代格式（配转写的视频、播客、PDF 或信息图）。\n每种格式为 AI 引擎开辟一条新的检索通道。"
              },
              "robots": {
                "add_sitemap_directive": "在 robots.txt 中添加 Sitemap 指令：\n  Sitemap: https://yoursite.com/sitemap.xml",
                "create": "在站点根目录创建 robots.txt 文件。\n最简示例：\n  User-agent: *\n  Allow: /\n  Sitemap: https://yoursite.com/sitemap.xml",
                "unblock_bots": "如需放行这些 AI bot，请在 robots.txt 中移除或修改对应的 Disallow 规则。\n放行 GPTBot 示例：\n  User-agent: GPTBot\n  Allow: /",
                "unblock_wildcard": "如果希望 AI 爬虫索引站点，请将 'User-agent: *' 下的 'Disallow: /' 改为 'Allow: /'。\n如需限制特定 bot，可以单独配置规则而不是整体禁用。",
                "add_ai_txt": "建议在站点根目录添加 ai.txt 文件（规范：spawning.ai/ai-txt），\n独立于 robots.txt 声明 AI 爬虫策略。"
              },
              "schema_kb": {
                "add_breadcrumb_schema": "为 HTML 面包屑添加配套的 BreadcrumbList 结构化数据：\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"BreadcrumbList\",\n    \"itemListElement\": [\n      {\"@type\": \"ListItem\", \"position\": 1, \"name\": \"Home\", \"item\": \"https://yoursite.com\"},\n      {\"@type\": \"ListItem\", \"position\": 2, \"name\": \"Products\", \"item\": \"https://yoursite.com/products\"}\n    ]\n  }\n  </script>",
                "add_breadcrumbs": "添加面包屑导航，帮助 AI 引擎理解站点结构：\n  1. 在页面可见处加入面包屑：Home > Category > Page\n  2. 同步添加 BreadcrumbList JSON-LD",
                "add_org_field": "在 Organization JSON-LD 中补充 \"{field}\" 字段，以提升知识面板入选概率。",
                "add_org_fields": "补充更多字段，强化知识面板入选条件：\n  \"address\": {\"@type\": \"PostalAddress\", \"streetAddress\": \"...\", \"addressLocality\": \"...\"},\n  \"telephone\": \"+1-xxx-xxx-xxxx\",\n  \"foundingDate\": \"2020\",\n  \"sameAs\": [\"https://twitter.com/...\", \"https://linkedin.com/...\"]",
                "add_organization": "添加 Organization 结构化数据，争取进入知识面板：\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"logo\": \"https://yoursite.com/logo.png\",\n    \"description\": \"What your company does\",\n    \"sameAs\": [\"https://twitter.com/you\", \"https://linkedin.com/company/you\"]\n  }\n  </script>"
              },
              "search_reg": {
                "bing_webmaster": "在 Bing Webmaster Tools 注册站点（https://www.bing.com/webmasters）：\n  1. 添加站点并完成所有权验证\n  2. 提交 sitemap.xml\n  3. 这一步必不可少——Bing 索引支撑 Microsoft Copilot、ChatGPT（基于 Bing 检索）\n     以及其他以 Bing 为搜索后端的 AI 助手。",
                "google_console": "在 Google Search Console 注册站点（https://search.google.com/search-console）：\n  1. 添加资源（URL 前缀或域名）\n  2. 通过 meta 标签、DNS 或 HTML 文件完成所有权验证\n  3. 在 Sitemaps 一栏提交 sitemap.xml\n  4. 监控索引状态并修复抓取错误\n这一步非常关键——Google AI Overviews 与 SGE 都从 Google 索引中取数据。",
                "indexnow": "配置 IndexNow，让 Bing、Yandex 等搜索引擎即时索引新内容：\n  1. 在 https://www.indexnow.org/ 申请 API key\n  2. 将密钥文件放在站点根目录：https://yoursite.com/{key}.txt\n  3. 内容变更时通知搜索引擎：\n     POST https://api.indexnow.org/indexnow\n     {\"host\": \"yoursite.com\", \"key\": \"your-key\", \"urlList\": [\"https://yoursite.com/updated-page\"]}\n  4. 许多 CMS 插件（例如 WordPress）已内置 IndexNow 支持。",
                "submit_all": "仅有 sitemap.xml 和 robots.txt 文件是不够的。\n还需要在各平台注册并主动提交：\n  \n  Google Search Console → 提交 sitemap → 支撑 Google AI Overviews / SGE\n  Bing Webmaster Tools  → 提交 sitemap → 支撑 Copilot、ChatGPT（Bing 后端）\n  IndexNow              → 自动通知    → Bing、Yandex、Naver 即时索引\n  \n不主动提交也可能被搜索引擎自然发现 sitemap，\n但主动提交能显著提升索引速度与可靠性。"
              },
              "sitemap": {
                "add_lastmod": "为 sitemap 中每个 <url> 节点补充 <lastmod>：\n  <url>\n    <loc>https://yoursite.com/page</loc>\n    <lastmod>2025-01-15</lastmod>\n  </url>",
                "create_file": "在站点根目录创建 sitemap.xml，示例：\n  <?xml version=\"1.0\" encoding=\"UTF-8\"?>\n  <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n    <url>\n      <loc>https://yoursite.com/</loc>\n      <lastmod>2025-01-15</lastmod>\n    </url>\n  </urlset>\n大多数 CMS（WordPress、Next.js 等）可以自动生成 sitemap。"
              },
              "social": {
                "add_sameas": "在 Organization JSON-LD 中通过 sameAs 关联各社交平台资料：\n  \"sameAs\": [\n    \"https://twitter.com/yourbrand\",\n    \"https://linkedin.com/company/yourbrand\",\n    \"https://github.com/yourbrand\",\n    \"https://facebook.com/yourbrand\"\n  ]\n这能帮助 AI 引擎跨平台确认你的实体身份。",
                "add_twitter_card": "在 <head> 中添加 Twitter card 标签：\n  <meta name=\"twitter:card\" content=\"summary_large_image\" />\n  <meta name=\"twitter:site\" content=\"@yourhandle\" />\n  <meta name=\"twitter:title\" content=\"Page Title\" />\n  <meta name=\"twitter:description\" content=\"Page description\" />\n  <meta name=\"twitter:image\" content=\"https://yoursite.com/image.jpg\" />"
              },
              "structured": {
                "add_product_reviews": "为 Product schema 添加评论和综合评分：\n  \"aggregateRating\": {\"@type\": \"AggregateRating\", \"ratingValue\": \"4.6\", \"reviewCount\": \"128\"},\n  \"review\": [{\"@type\": \"Review\", \"author\": ..., \"reviewRating\": ...}]",
                "upgrade_to_granular": "将通用的 WebPage/CreativeWork 升级为精细化类型：\n  • 教程内容 → HowTo + 步骤列表\n  • 问答页面 → FAQPage + Question/Answer 对\n  • 产品页面 → Product + offers + aggregateRating\n  • 文章页面 → NewsArticle 或 BlogPosting\n精细化类型让 AI 引擎能提取更丰富的信息。",
                "add_organization_jsonld": "在 <head> 中添加 JSON-LD 结构化数据，Organization 示例：\n  <script type=\"application/ld+json\">\n  {\n    \"@context\": \"https://schema.org\",\n    \"@type\": \"Organization\",\n    \"name\": \"Your Company\",\n    \"url\": \"https://yoursite.com\",\n    \"description\": \"What your company does\"\n  }\n  </script>\n使用 Google Rich Results Test 校验：https://search.google.com/test/rich-results"
              },
              "tech_crawl": {
                "add_rss_feed": "为内容添加 RSS 或 Atom feed，并在 <head> 中引用：\n  <link rel=\"alternate\" type=\"application/rss+xml\" title=\"RSS\" href=\"/feed.xml\" />\n大多数 CMS 可自动生成 feed；静态站点可使用 eleventy-rss 等工具。",
                "broken_canonical": "canonical URL {canonical_url} 已失效。请修复目标页面，或将 canonical 更新为可访问的 URL。",
                "enable_http2": "在服务器启用 HTTP/2 以加快抓取：\n  Nginx：listen 443 ssl http2;\n  Apache：Protocols h2 http/1.1\n  也可以使用 Cloudflare 等 CDN 自动启用 HTTP/2。",
                "fix_canonical_chain": "修复 canonical 链——每个页面的 canonical 应直接指向最终 URL，而不是经过中间跳转。\n将各页面的 canonical 设置为自身 URL 或最终目标。",
                "reduce_redirects": "将重定向链压缩为单跳（A -> B，而不是 A -> B -> C -> D）。\n更新服务器配置，直接重定向到最终 URL。",
                "feed_full_content": "在 feed 中发布完整内容而非摘要。AI 代理更倾向直接提取完整文本，\n无需逐条跟随链接抓取。",
                "feed_expand_content": "你的 feed 仅发布标题/片段。请切换到完整内容，\n让 AI 代理和聚合器无需抓取 HTML 即可索引实际文章。",
                "add_api_docs": "发布机器可读的数据 feed 和集成文档，让 AI 代理能以编程方式消费你的数据\n（如 /openapi.json、/api/v1、/developers）。"
              },
              "url_norm": {
                "lowercase_url": "确保服务器对 URL 大小写做归一化（统一为小写）。Nginx 示例：\n  location ~ [A-Z] { rewrite ^(.*)$ $scheme://$host$uri_lowercase permanent; }",
                "www_redirect": "配置 301 重定向，让其中一个版本指向另一个：\n  # Nginx：将 www 重定向到非 www\n  server {{ server_name www.{host}; return 301 https://{host}$request_uri; }}\n然后将 canonical 设置为优选版本。"
              },
              "well_known": {
                "add_security_txt": "建议添加 .well-known/security.txt（RFC 9116）作为信任信号：\n  Contact: mailto:security@yoursite.com\n  Preferred-Languages: en\n  Canonical: https://yoursite.com/.well-known/security.txt",
                "fix_invalid_json": "用 JSON 校验工具检查并修复 {path} 中的语法错误。"
              }
            },
            "scoreCard": {
              "title": "AI 可见性得分",
              "description": "您的网站对 AI 搜索的优化程度",
              "grade": "等级"
            },
            "summary": {
              "passed": "通过",
              "warnings": "警告",
              "failed": "失败",
              "info": "信息",
              "totalChecks": "总检查项",
              "overview": "汇总概览",
              "allPassed": "全部通过"
            },
            "detailedResults": "详细结果",
            "fix": "修复建议：",
            "buttons": {
              "checkAnother": "返回",
              "getHelp": "获取优化帮助"
            },
            "error": {
              "noData": "未找到 GEO 检查数据。请先运行检查。"
            },
            "loginToView": "登录查看完整结果",
            "loginToViewDesc": "登录以查看所有详细结果和建议",
            "loginButton": "登录",
            "paywall": {
              "lockedCount": "还有 {{count}} 项检测结果已锁定",
              "subtitle": "开通会员即可解锁所有检测详情与优化建议",
              "viewAll": "查看全部 →",
              "perCategoryHint": "查看 {{total}} 项检查中的 2 项（会员可查看全部）",
              "unlockCategory": "升级会员解锁本项检测 →",
              "memberOnly": "此检测项需要开通会员",
              "upgradePro": "订阅会员"
            },
            "upgradeHint": {
              "fixPrompt": "升级会员获取修复建议 →"
            },
            "groupProgress": {
              "title": "分类进度"
            },
            "categories": {
              "infraProtocols": "基础协议与可抓取性",
              "pageBasics": "页面基础与移动体验",
              "aiProtocols": "AI 专属协议与抓取",
              "structuredSemantic": "结构化与语义",
              "contentQuality": "内容质量与可读性",
              "techRobustness": "技术健壮性与媒体",
              "authorityExternal": "权威与外部信号",
              "other": "其它"
            },
            "categoryLabels": {
              "HTTPS": "HTTPS 安全协议",
              "robots.txt": "robots.txt",
              "llms.txt": "llms.txt",
              ".well-known Discovery": ".well-known 发现",
              "sitemap.xml": "sitemap.xml 站点地图",
              "Search Engine & AI Platform Registration": "搜索引擎 / AI 平台收录",
              "Structured Data": "结构化数据（JSON-LD）",
              "Meta Tags": "Meta 标签",
              "Content Accessibility": "内容可读性",
              "AI Crawl Readiness": "AI 爬虫可访问性",
              "Content Quality for AI": "内容质量（面向 AI）",
              "Technical Crawlability": "技术抓取能力",
              "Authority & Trust Signals": "权威与信任信号",
              "AI-Specific Optimization": "AI 专项优化",
              "Social Signals": "社交信号",
              "AI Answer Format Optimization": "AI 答案格式优化",
              "Schema Breadcrumbs & Knowledge Panel": "Schema / 知识面板",
              "Mobile-Friendliness & Page Weight": "移动端友好性与页面体积",
              "URL Normalization": "URL 规范化",
              "Outbound Links & Media": "出站链接与媒体",
              "Multilingual Content Depth": "多语言内容深度",
              "Cross-Platform Content Distribution": "跨平台内容分发",
              "Multi-Page Sampling": "多页面采样",
              "Brand Entity KG": "品牌实体与知识图谱",
              "Trust & Safety": "信任与安全信号"
            },
            "header": {
              "rerunPlaceholder": "输入新的 URL 重新检测",
              "rerun": "重新检测",
              "modeLabel": "检测模式",
              "modeDefault": "标准检测",
              "modeLockedHint": "升级会员解锁此模式",
              "placeholderCompare": "https://a.com, https://b.com, https://c.com",
              "placeholderKeywords": "关键词（可选，逗号分隔）",
              "placeholderEntity": "品牌 / 产品 / 人物 名称",
              "entityTypeLabel": "实体类型",
              "entityType": {
                "brand": "品牌",
                "product": "产品",
                "person": "人物"
              },
              "compareHint": "用逗号或空格分隔 2-5 个网址",
              "visibilityHint": "关键词留空则自动生成；多个关键词用逗号分隔",
              "entityHint": "输入要审计的品牌 / 产品 / 人物名称"
            },
            "visuals": {
              "robots": {
                "title": "AI 爬虫许可矩阵",
                "filePresent": "robots.txt · 文件存在",
                "fileMissing": "robots.txt · 文件缺失",
                "sitemapRef": "sitemap 引用 ✓",
                "noSitemapRef": "缺少 sitemap 引用",
                "wildcardWarning": "通配符规则 User-agent: * 禁止所有爬虫。下方标为「继承通配符」的机器人在你覆盖之前实际上都是被屏蔽的。",
                "legend": {
                  "allowed": "已允许",
                  "blocked": "已屏蔽",
                  "inherited": "继承通配符",
                  "unknown": "未知"
                }
              },
              "meta": {
                "title": "Meta 标签覆盖",
                "subtitle": "AI 引擎用于生成摘要的 6 个信号",
                "passCount": "{{pass}}/{{total}} 通过",
                "items": {
                  "title": { "help": "页面标题标签" },
                  "description": { "help": "Meta 描述" },
                  "canonical": { "help": "规范 URL" },
                  "og": { "help": "用于社交和 AI 摘要的 og:* 标签" },
                  "lang": { "help": "语言声明" },
                  "hreflang": { "help": "多语言替代版本" }
                }
              },
              "platform": {
                "titleCross": "跨平台存在度",
                "titleSocial": "社交信号覆盖",
                "subtitle": "AI 引擎会训练的平台来源",
                "notDetected": "{{name}} 未检测到"
              }
            },
            "fixPackage": {
              "download": "修复包",
              "downloading": "生成中...",
              "title": "下载修复包",
              "upgradeRequired": "此功能需要 Starter 或更高级别的会员。",
              "error": "修复包下载失败"
            },
            "shareExport": {
              "title": "分享和导出",
              "copied": "链接已复制到剪贴板！",
              "copyLink": "复制链接",
              "exportPDF": "导出 PDF",
              "exportPDFLoading": "导出 PDF 中...",
              "exportCSV": "导出 CSV",
              "shareSocial": "分享到社交媒体",
              "share": "分享",
              "downloadReport": "下载报告",
              "downloadReportLoading": "正在生成报告…"
            },
            "pdfReport": {
              "title": "GEO 就绪度检测报告",
              "subtitle": "衡量网站在 AI 搜索引擎中的可见度与优化程度",
              "targetSite": "目标网站",
              "generatedAt": "生成时间",
              "tier": "报告等级",
              "overallScore": "综合得分",
              "scoreInterpretation": "得分解读",
              "scoreLevels": {
                "excellent": "优秀 — 网站对 AI 搜索引擎已有良好优化，建议保持监控并持续微调。",
                "good": "良好 — 基础要素基本到位，再修复几项重点问题即可进入顶级梯队。",
                "average": "一般 — 存在多项重要信号缺失，建议优先修复下方标红/警告项以提升可见度。",
                "poor": "待改进 — AI 引擎对您网站内容的呈现度不足，建议尽快处理失败项。",
                "critical": "严重不足 — 网站对 AI 引擎几乎不可见，建议进行一次完整的 GEO 优化。"
              },
              "groupSection": "分类得分概览",
              "groupLabel": "分类",
              "recommendationsSection": "优先修复建议",
              "topFixesIntro": "下列是对得分影响最大的问题，按严重程度排序，优先处理这些项收益最高。",
              "detailSection": "检测详情",
              "appendixSection": "关于本报告",
              "appendixBody": "本报告由 GEO Checker 生成，分数反映您的网站对 ChatGPT、Perplexity、Google AI Overviews、Copilot 等 AI 搜索引擎最佳实践的遵循程度。完成修复后可重新运行检测查看进展。",
              "footer": "GEO Checker · © {{year}} · 保留所有权利",
              "fileName": "GEO就绪度报告",
              "fixLabel": "修复建议",
              "noFix": "暂无具体修复建议。",
              "noFailItems": "未发现失败或警告项，状态良好！",
              "lockedNotice": "本报告中有 {{count}} 个分类分组处于锁定状态，升级会员可解锁完整结果。",
              "statusLabels": {
                "pass": "通过",
                "warn": "警告",
                "fail": "失败",
                "info": "信息"
              },
              "tierLabels": {
                "free": "免费版",
                "pro": "检测会员",
                "starter": "Starter",
                "growth": "Growth",
                "scale": "旗舰版"
              },
              "pageOf": "第 {{current}} 页 / 共 {{total}} 页",
              "coverBadge": "GEO 就绪度检测报告",
              "headerSite": "检测目标"
            }
          },
} as const;

export default zhResult;
