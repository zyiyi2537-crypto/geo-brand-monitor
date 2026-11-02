"""对外开放薄层(embed)—— 让外部 agent(小龙虾)链接本 GEO agent。

Agent integration behavior is defined by the public API. Core:
  - tokens.py   1 年期账号 token 签发(领号)+ 校验(每请求,验签 + 查 enabled)
  - deps.py     embed token → AgentDeps(account_id 后端注入,caps 收敛)
  - api.py      /api/agent/v1/*(chat / data / meta)对外稳定面
"""
