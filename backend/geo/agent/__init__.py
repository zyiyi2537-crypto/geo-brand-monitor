"""GEO 优化 Agent — 对话式 GEO/AEO 优化助手(Pydantic AI 实现)。

设计见 docs/实现设计-Agent.md、docs/最佳方案-GEO优化Agent.md。

分层:
  deps.py     AgentDeps(租户上下文) + assert_owns(归属校验)
  model.py    DeepSeek 模型工厂(OpenAI 兼容)
  agent.py    build_agent():Pydantic AI Agent + 工具注册
  tools.py    工具实现(@RunContext[AgentDeps];包装现有 service)
  methods.py  Method 层(不暴露给模型:鉴权/护栏/发布/调度/推送)
  api.py      /api/agent/* 路由(chat SSE / diagnose)

框架仅出现在 model/agent/tools;deps/methods/api 与框架解耦,换框架不动它们。
"""
