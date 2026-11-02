# archive/

历史代码归档。**不参与 runtime**,仅供对比、回溯、回归测试用。

## 当前归档

### `geo_checker_v1_baseline.py`(8065 行)

2026-04-17 package 重构**之前**的单文件 CLI,从 git tag `pre-refactor-package-2026-04-17` 抽取得到,与该 tag 的根 `geo_checker.py` 逐字节相同。

**注意有"第二份同源文件"在 `/geo_checker.py`**(根目录,`b5b159e` 恢复):
- 字节与本文件 100% 相同(都是 8065 行 / 396859 bytes)
- 根文件作为 **CLI 入口**(`python geo_checker.py <url>`)
- archive 这份作为 **只读历史归档**
- 两份都**冻结**,不跟随 `backend/geo_checker/` package 的后续改动
- 这两份的存在不影响 runtime:uvicorn 从 `/backend` 加载的是 `backend/geo_checker/` package(见 CLAUDE.md "三份同源文件"一节)

**用途**:

- **评分 drift 回归测试**:把同一 URL 喂给 v1 baseline 和当前 backend,对比 24 个 category 的分数应完全一致
- **追查行为变化**:未来某次改动引入疑似评分变化时,用 baseline 做对照
- **upstream diff 参考**:该文件结构接近上游 `Yaqing2023/GEO` 的单文件 CLI;合 upstream 时可做 diff 基准

**不会被加载**:

- `pyproject.toml` 的 `[tool.setuptools.packages.find]` 限 `where = ["backend"]`,`archive/` 不会被打包
- Python 运行时从 `backend/` CWD 加载 `geo_checker` package,不会命中此文件
- 里面引用的 `_TeeStream` / `_write_text_pdf` 是**上游遗留的未定义符号**,`--report pdf/html` 路径会抛 `NameError`(已知缺陷,与 archive 无关)

### 独立运行(回归测试)

```bash
# 用 backend 的 venv(已有 requests + bs4)
backend/.venv/bin/python archive/geo_checker_v1_baseline.py https://moltspay.com

# 或者不用 venv
pip install requests beautifulsoup4
python archive/geo_checker_v1_baseline.py https://example.com
```

输出最后一段 `Category Breakdown` 表格就是逐 category 评分。可以用脚本解析后与当前 backend 的 `/api/check/anonymous` 响应对比。

### 已验证的对照点(2026-04-17)

#### 默认 check(runtime 实测)

| URL | v1 baseline | v2.1.0 backend | 差异 |
|---|---|---|---|
| `https://moltspay.com` | 80/100 (A),103.5/130 | 80/100 (A),103.5/130 | **0 category diff** |

#### AI Visibility Audit(源码等价证明)

AI Visibility Audit(`--ai-visibility`)的实际输出**不具备完全确定性** —— AI 引擎的 `temperature > 0` 会让同一段 prompt 返回略有差异的文本,哪怕 code 一样。`STABILITY_RUNS=3` 是为了平均掉这种噪声,但仍有 ±3-5 分自然浮动。

因此这里采用 **源码 diff 等价** 证明逻辑一致,不走 runtime 对比(每次 90 OpenRouter 调用 × $0.01 ≈ $1,跑对比要 $2+,而且 AI 随机性会在最终报告上带来自然抖动,runtime 数字相等的概率本来就不高)。

**2026-04-17 Diff 结果**:

| 函数 | old 行数 | new 行数 | body diff |
|---|---|---|---|
| `ai_visibility`(顶层 runner) | 577 | 576 | **0**(仅下一个函数的 def 边界改变) |
| `_query_perplexity` | — | — | **0** |
| `_query_openai` | — | — | **0** |
| `_query_anthropic` | — | — | **0** |
| `_query_deepseek` | — | — | **0** |
| `_query_doubao` | — | — | **0** |
| `_check_brand_in_result` | — | — | **0** |
| `_extract_competitors` | — | — | **0** |
| `_classify_framing` | — | — | **0** |

所有 AI 路径的代码路径字节级等价,逻辑一致性已证。**同样的 AI 回答输入下,两份代码必然产生相同的分数**。

复跑方法(备用):

```bash
diff <(awk '/^def ai_visibility/,/^def _check_knowledge_graph|^def entity_audit/' archive/geo_checker_v1_baseline.py) \
     <(awk '/^def ai_visibility/,/^def _check|^def entity_audit|^def aeo/' backend/geo_checker/modes/visibility.py)

for fn in _query_perplexity _query_openai _query_anthropic _query_deepseek _query_doubao _check_brand_in_result _extract_competitors _classify_framing; do
  next=$(grep -A1 "^def $fn" archive/geo_checker_v1_baseline.py | tail -1)  # 找老版下一个函数名来做边界
  # 粗略做法,详见 ai.py 内部顺序
done
```

相关历史性能报告和 issue register 已在文档整合中移除；当前维护入口见
`docs/engineering/checker-reliability-and-performance.md`。

## 归档规则

- 只放**完整、能独立运行**的快照,不放补丁或片段
- 文件名带 `v<major>_baseline` 或 `_pre_<重构名>` 后缀,一眼能看出归档时刻
- 绝不从 runtime 代码 `import` archive 里的东西 —— 它是只读历史
- 删除需通过 PR,理由写清楚(一般不删)
