const zhKnowledge = {
"geoKnowledge": {
            "title": "资源中心",
            "description": "掌握 GEO + AEO：从 AI 搜索引擎赢得可见性与推荐的聪明方法",
            "sections": {
              "about": "理解 GEO & AEO",
              "whatIsGeo": "什么是 GEO & AEO？",
              "whatIsGeoBody": "GEO（生成式引擎优化）和 AEO（答案引擎优化）是专为 AI 搜索引擎和 AI 助手（ChatGPT、Perplexity、Google AI Overviews、Gemini、Claude、Copilot 等）设计的优化实践。GEO 专注于让你的品牌在 AI 引擎中可见并可被引用。AEO 更进一步 — 优化你的内容，让 AI 不仅能找到你，更能直接理解、信任并选择你的品牌作为用户问题的最佳答案。传统 SEO 优化的是搜索结果页上的蓝色链接，而 GEO + AEO 优化的是 AI 实际生成的那段答案。",
              "whyGeoImportant": "为什么 GEO + AEO 重要",
              "whyGeoPoints": [
                "传统搜索流量正在被 AI 生成的答案取代 — 如果你不在答案里，就是彻底隐形。",
                "AI 引擎每次查询只引用极少量可信来源 — 进入这个名单就锁定了品类权威。",
                "一旦 AI 模型将你识别为品牌实体，它会在无数相关查询中反复推荐你，产生复利效应。",
                "GEO + AEO 的先行者能在竞争对手反应过来之前锁定品类领导地位。"
              ],
              "strategies": "GEO 策略",
              "contentLocalization": "权威内容与实体清晰度",
              "contentLocalizationDesc": "AI 引擎只引用它能够验证的内容。围绕品牌、产品和所在品类建立深度第一方内容，提供清晰的实体信号，让大模型能够解析并信任。",
              "contentLocalizationPoints": [
                "围绕核心话题产出深度、专家级的原创内容，拒绝稀薄营销文案",
                "添加 Organization / Product 结构化数据（JSON-LD）与 llms.txt 文件",
                "在 Wikipedia、Wikidata、Reddit、GitHub 及权威目录站建立品牌存在"
              ],
              "technicalOptimization": "技术基础与 AI 可抓取性",
              "technicalOptimizationDesc": "AI 爬虫拿不到你的内容就无法引用你。确保 GPTBot、ClaudeBot、PerplexityBot、Google-Extended 能够真实抓取并渲染你的页面。",
              "technicalOptimizationPoints": [
                "在 robots.txt 中放行 AI 爬虫（GPTBot、ClaudeBot、PerplexityBot、Google-Extended）",
                "提供快速的服务端渲染 HTML，避免纯 JS 页面——AI 爬虫不会执行 JavaScript",
                "使用语义化 HTML 与干净的标记，让大模型能把页面解析成结构化事实"
              ],
              "keyData": "GEO 关键指标",
              "importantMetrics": "该衡量什么",
              "regionalTraffic": "AI 引用率",
              "regionalTrafficDesc": "当 AI 引擎回答品牌相关或品类相关问题时，把你的站点作为来源引用的频率。",
              "languagePreference": "答案提及率",
              "languagePreferenceDesc": "在相关查询中，你的品牌实际出现在 AI 生成答案里的比例——无论是否附带直接引用链接。",
              "searchTrends": "竞品声量占比",
              "searchTrendsDesc": "AI 模型会和你一起提到哪些竞品、出现频率如何——这才是品类心智的真实基准。"
            },
            "tabs": {
              "overview": "概览",
              "metrics": "指标词典"
            },
            "metrics": {
              "title": "GEO 检测指标词典",
              "description": "GEO 就绪度报告里的每一项检测——它在测什么、为什么对 AI 可见性重要、具体怎么改善，逐项讲清楚。",
              "field": {
                "measures": "测什么",
                "why": "为什么重要",
                "scoring": "评分逻辑"
              },
              "categories": {
                "crawlability": {
                  "title": "一、基础可抓取性",
                  "description": "决定 AI 爬虫能否到达并索引你页面的底层信号。这一层不过，后面的一切都白搭。",
                  "items": {
                    "https": {
                      "name": "HTTPS 安全协议",
                      "measures": "检测你的站点是否通过 HTTPS 提供服务、TLS 证书是否合法有效。",
                      "why": "AI 引擎爬虫（OpenAI GPTBot、Anthropic ClaudeBot、Perplexity、Google-Extended）会直接跳过非 HTTPS 站点。明文 HTTP 页面无论是在训练阶段还是实时检索阶段都会被降权或直接忽略。",
                      "scoring": "HTTPS 且证书有效 → PASS；HTTP 自动重定向到 HTTPS 可接受；纯 HTTP 或证书过期 → FAIL。"
                    },
                    "robots": {
                      "name": "robots.txt 爬虫规则",
                      "measures": "检测 robots.txt 是否存在、语法是否合法、是否明确放行主流 AI 爬虫（GPTBot、ClaudeBot、PerplexityBot、Google-Extended、CCBot）。",
                      "why": "AI 爬虫默认尊重 robots.txt。一条 Disallow: / 或 User-agent: GPTBot 的屏蔽就能让 OpenAI 永远看不到你的内容，相当于主动从 AI 视野里消失。",
                      "scoring": "文件存在且放行所有主流 AI 爬虫 → PASS；屏蔽 1–2 个次要爬虫 → WARN；屏蔽 GPTBot / ClaudeBot / CCBot 中任意一个 → FAIL。"
                    },
                    "sitemap": {
                      "name": "sitemap.xml 站点地图",
                      "measures": "检测 sitemap.xml 是否存在、格式合法、URL 数量合理，以及是否在 robots.txt 中被引用。",
                      "why": "AI 爬虫通过 sitemap 发现你所有页面，而不是从首页顺链接爬。缺失 sitemap 意味着爬虫可能只抓到首页就离开，深度内容对 LLM 完全隐形。",
                      "scoring": "文件存在且 URL 数量合理 → PASS；存在但 URL 很少或格式异常 → WARN；缺失 → FAIL。"
                    },
                    "llms": {
                      "name": "llms.txt LLM 索引文件",
                      "measures": "检测根目录下是否存在 llms.txt。这是 2024 年提出的新协议，用 Markdown 格式告诉大模型你站点是什么、核心内容在哪里。",
                      "why": "llms.txt 给 AI 爬虫一份「策划过的导览地图」——它不用猜哪些页面是精华，直接按你列的顺序抓。Anthropic、Perplexity 等已开始支持或参考这个协议，先做先占位。",
                      "scoring": "文件存在 → PASS；缺失 → INFO（目前非强制，但成本低、先做先赢）。"
                    },
                    "aiCrawlerAccess": {
                      "name": "AI 爬虫实测可访问性",
                      "measures": "用 GPTBot、ClaudeBot、PerplexityBot 等真实 User-Agent 发 HTTP 请求，检查你的 WAF、Cloudflare Bot Fight、验证码是否把它们挡在门外。",
                      "why": "robots.txt 放行只是第一层——Cloudflare Bot Fight 或 AWS WAF 常常把所有非浏览器 UA 一律当恶意爬虫拦掉，AI 爬虫也会被误伤。robots 策略和边缘策略必须一致。",
                      "scoring": "所有 AI UA 返回 200 → PASS；部分被拦 → WARN；全部被拦 → FAIL。"
                    }
                  }
                },
                "structuredData": {
                  "title": "二、结构化数据",
                  "description": "让大语言模型不用从散文里猜你是谁、你卖什么——这些是机器可读的信号。",
                  "items": {
                    "jsonld": {
                      "name": "JSON-LD 结构化数据",
                      "measures": "检测首页是否有 JSON-LD 代码块，以及是否描述了 Organization、Product、WebSite 等 schema.org 类型，核心字段是否填齐。",
                      "why": "结构化数据是你能给 LLM 的最机器可读的信号。ChatGPT、Perplexity、Google AI Overviews 都依赖 schema.org 标记来确认实体身份和抽取事实——缺了它，模型只能从散文里猜，猜错的代价就是被加免责声明或干脆忽略。",
                      "scoring": "Organization + Product / WebSite / FAQ 中任一，且核心字段齐全 → PASS；只有单个瘦身块 → WARN；完全没有 → FAIL。"
                    },
                    "metaTags": {
                      "name": "Meta 标签覆盖",
                      "measures": "检测首页的 title、meta description、canonical、viewport、Open Graph（og:title / og:description / og:image）、以及 Twitter Card 标签。",
                      "why": "Meta 标签是 AI 决定页面是否相关时看的那两行摘要。描述缺失意味着模型得自己生成一段——或者干脆跳过这个页面。og:image 也是 AI 聊天答案里链接预览卡片渲染的底图。",
                      "scoring": "6 条核心信号全都有 → PASS；4–5 条 → WARN；少于 4 条 → FAIL。"
                    },
                    "breadcrumbs": {
                      "name": "面包屑与知识面板标记",
                      "measures": "检查 BreadcrumbList JSON-LD、可见的面包屑导航，以及知识面板友好的标记（`sameAs`、`logo`、`SearchAction`）。",
                      "why": "面包屑帮 AI 理解你的站点结构——一个页面在品类树的什么位置。知识面板标记是 Google 和 Perplexity 构造查询旁那个「摘要框」的原料。两者都会随时间累积发挥作用。",
                      "scoring": "两类信号都有 → PASS；只有其中一类 → WARN；都没有 → FAIL。"
                    },
                    "answerFormat": {
                      "name": "AI 答案格式优化",
                      "measures": "检测内容是否以 LLM 容易直接引用的格式撰写——FAQ schema、问答模式、定义式开头段落、简洁直接的答案。",
                      "why": "LLM 偏好可以直接引用、自成一句的源。`「X 是一种 [品类]，它 [价值主张]」` 比把答案埋在营销段落里好得多。FAQ schema 明确标记了问答对，告诉 AI 这些是可抽取的答案。",
                      "scoring": "有 FAQ schema + 清晰的定义式开头 → PASS；部分具备 → WARN；完全没有可引用结构 → FAIL。"
                    }
                  }
                },
                "authority": {
                  "title": "三、权威信号",
                  "description": "LLM 用来判断你是否值得被推荐的站外证据——在训练语料里、百科里、评论平台里、媒体里的存在感。",
                  "items": {
                    "commonCrawl": {
                      "name": "AI 训练数据收录 (Common Crawl)",
                      "measures": "在 Common Crawl 最新一期全网快照里查你的域名，统计有多少页面被采入这个公开网页语料库。",
                      "why": "Common Crawl 是 ChatGPT、Claude、LLaMA 以及几乎所有开源 LLM 的训练数据。如果你没进 Common Crawl，这些模型在训练时从没见过你——用户问到品牌相关问题时，它们对你零记忆，结果要么加免责声明要么直接忽略。",
                      "scoring": "找到页面 → PASS；未收录但域名 < 60 天 → INFO（新站正常）；未收录且老站 → WARN；未收录 + robots.txt 屏蔽了 CCBot → FAIL。"
                    },
                    "wikipedia": {
                      "name": "Wikipedia / Wikidata 实体",
                      "measures": "检测你的品牌或产品是否在 Wikipedia（中英文）有词条，以及是否有 Wikidata Q-item。",
                      "why": "Wikipedia 和 Wikidata 是 LLM 用来验证实体的最权威结构化源。如果 ChatGPT 能在 Wikidata 上查到你，它就把你当真实实体对待；否则你会得到 `我对这个品牌不太确定` 的免责声明——这基本等于把推荐机会让出去。",
                      "scoring": "Wikipedia 词条 + Wikidata Q-item 都有 → PASS；只有其一 → WARN；都没有 → FAIL。"
                    },
                    "knowledgeGraph": {
                      "name": "Google 知识图谱收录",
                      "measures": "通过 schema.org 标记和 Google Knowledge Graph API 查询你的品牌是否在 Google 知识图谱里——就是那个出现在 Google 搜索右侧的实体侧栏。",
                      "why": "Google 的知识图谱直接喂给 Google AI Overviews、SGE 和 Gemini。在图谱里的实体会被引用，不在的就不会。同时它也为其他把 Google 结果作为参考的 LLM 播下了品牌事实种子。",
                      "scoring": "实体被找到且字段丰富 → PASS；部分覆盖 → WARN；未找到 → FAIL。"
                    },
                    "reviews": {
                      "name": "第三方评论与评分",
                      "measures": "检测你在所在品类的主流评论平台上是否有存在感——G2、Capterra、Trustpilot、Glassdoor、Yelp、TripAdvisor、CNET、Product Hunt 等。",
                      "why": "AI 引擎比较竞品时会给用户评论很高权重。G2 上有 100 条 4.5 星评论的品牌会被推荐，没有任何评论的会被跳过换成一个 `被真实用户验证过` 的品牌。LLM 在不同品类读的平台也不同。",
                      "scoring": "在 3+ 个品类相关平台有存在 → PASS；1–2 个 → WARN；都没有 → FAIL。"
                    },
                    "mentions": {
                      "name": "权威媒体与新闻提及",
                      "measures": "搜索高权重新闻和行业媒体中对你品牌的提及——WSJ、NYT、TechCrunch、Forbes、Bloomberg、行业分析师报告。",
                      "why": "权威性会复利累积。一篇 TechCrunch 文章的分量大于一百个随机博客的反链。训练在新闻数据集（GDELT、CCNews、RSS dumps）上的 LLM 把这些提及当作构建品牌实体画像的事实基准。",
                      "scoring": "3+ 条高权重提及 → PASS；1–2 条 → WARN；都没有 → FAIL。"
                    }
                  }
                },
                "visibility": {
                  "title": "四、AI 直接可见性",
                  "description": "滞后指标——衡量真实 AI 引擎在回答品类问题时是否真的提到并引用你。上面所有项都是先行指标，这一层才是真正决定生意的数字。",
                  "items": {
                    "citationRate": {
                      "name": "AI 引用率",
                      "measures": "通过 OpenRouter 把一组品牌相关和品类相关的问题发给 Perplexity，统计你的域名作为引用来源出现的频率。",
                      "why": "最终考试：用户在品类问题里问 AI，AI 会不会指向你？词典里其它所有项都是先行指标，引用率才是真正驱动收入的滞后指标。",
                      "scoring": "≥80% 引用率 → A（优秀）；60–79% → B；40–59% → C；20–39% → D；<20% → F。"
                    },
                    "answerInclusion": {
                      "name": "答案提及率",
                      "measures": "比引用率更柔和的指标——统计你的品牌名字是否在 AI 生成的答案里出现，无论是否带可点击的引用链接。",
                      "why": "没带引用链接的提及照样能赢心智。用户读到 `像 X、Y、Z 这样的品牌都…` 即使不点击也会记住名字。提及率是引用率的先行指标——先被提起，后被引用。",
                      "scoring": "≥60% 相关查询里被提及 → PASS；30–59% → WARN；<30% → FAIL。"
                    },
                    "shareOfVoice": {
                      "name": "竞品声量占比",
                      "measures": "在同一批品类查询里，统计哪些竞品品牌和你一起被提及、各自出现频率如何。",
                      "why": "你不只想被提及——你想在主要竞品**之前**被提及、**比他们更频繁**被提及。这个指标告诉你：AI 把你感知成品类领导者、挑战者、还是陪跑？",
                      "scoring": "你的品牌在被提及频率前 3 → PASS；在前 10 → WARN；没被提及 → FAIL。"
                    },
                    "sentimentFraming": {
                      "name": "品牌情感与框架",
                      "measures": "分析 AI 描述你品牌时的情感基调和叙事框架——是 `创新领导者`、`挑战者`、`小众玩家`、`曾出过问题`、还是 `有争议`？",
                      "why": "AI 在训练期捕捉到的品牌框架会固定好几年。训练数据里被框为 `创新者` 的品牌会被主动推荐；被框为 `曾出过问题` 的品牌即使情况早已改善，也会被加免责声明。",
                      "scoring": "≥60% 正面或中性框架 → PASS；30–59% → WARN；<30% 或频繁被加免责声明 → FAIL。"
                    },
                    "contentGaps": {
                      "name": "内容缺口",
                      "measures": "识别你品类里 AI 找不到好答案的那些问题——这些是竞品写了权威内容而你没有的地方。",
                      "why": "每一个未填的内容缺口都是竞品占掉的用户旅程。填补缺口是最直接的提升引用率方式——新页面被抓取后 AI 会立刻开始指向它。",
                      "scoring": "0 个重大缺口 → PASS；1–3 个 → WARN；4+ → FAIL。"
                    }
                  }
                },
                "entity": {
                  "title": "五、实体识别度",
                  "description": "大语言模型是否把你品牌当作一个真实、独立、能被自信描述的实体——这是 AI 可见性所有其它层面的地基。",
                  "items": {
                    "entityClarity": {
                      "name": "实体清晰度",
                      "measures": "让 AI 描述你的品牌，然后打分看描述是否准确、具体、完整。模型知道你做什么、服务谁、和别人有什么不同吗？",
                      "why": "如果 AI 无法简洁地描述你是什么，它就无法推荐你。`我觉得他们做一些和 AI 相关的东西` 属于失败状态——用户会重新提问，而竞品在 AI 犹豫的这几秒里就插队了。",
                      "scoring": "描述准确且具体 → PASS；模糊或部分错误 → WARN；困惑或完全不知道 → FAIL。"
                    },
                    "categoryAssociation": {
                      "name": "品类关联度",
                      "measures": "检测用户问品类问题时，AI 是否把你的品牌放进正确的心智格子。问 `最好的 X 工具` 时你会出现吗？问到错误品类时你是否缺席？",
                      "why": "大部分购买决策走的是品类意图。如果 AI 把你归到错误品类（或根本没品类归属），你对正在做调研的用户就是隐形的——他们永远看不到你的名字。",
                      "scoring": "≥70% 查询里被放进正确品类 → PASS；30–69% → WARN；<30% → FAIL。"
                    },
                    "platformCoverage": {
                      "name": "多平台覆盖",
                      "measures": "检测你在 LLM 训练最密集的平台上是否有经过验证的存在：Wikipedia、Wikidata、Crunchbase、LinkedIn、GitHub、Reddit、Product Hunt、Hacker News、行业目录。",
                      "why": "每多一个高权重平台都是 AI 用来构建你实体画像的一份交叉证据。覆盖 6+ 个平台的品牌会被自信地推荐；只有一个官网的会被当作未验证，推荐时会被加免责声明。",
                      "scoring": "覆盖 ≥6 / 10 个关键平台 → PASS；3–5 个 → WARN；<3 → FAIL。"
                    },
                    "recognitionRate": {
                      "name": "识别率",
                      "measures": "跨多个 AI 引擎和多种提问变体，统计模型能在不需要 URL 或额外消歧的情况下直接认出你品牌名的比例。",
                      "why": "识别是推荐的前提。如果 AI 每次都要反问 `你说的是哪个 X？`，用户就会流失到一个模型已经直接知道名字的品牌那里。",
                      "scoring": "≥80% 识别率 → PASS；50–79% → WARN；<50% → FAIL。"
                    },
                    "stability": {
                      "name": "答案稳定性",
                      "measures": "在同一个 AI 引擎上多次跑相同查询，检测答案是否一致。不稳定的答案说明训练期的 grounding 很薄弱。",
                      "why": "同一个问题一次给出 `X 是个好工具`、下一次给出 `没听说过 X`——用户会相信不确定的那次并流失。稳定即信任，信任才能换来推荐。",
                      "scoring": "≥90% 答案一致 → PASS；70–89% → WARN；<70% → FAIL。"
                    }
                  }
                }
              }
            }
          },
} as const;

export default zhKnowledge;
