"""Agent 评测骨架。

分两层(见 docs / memory[[reference_geo_agent_deploy]]):
- 组件级(test_routing.py):**无 LLM、确定性**,锁住 route_line + 业务线工具隔离机制,做 CI 回归闸门。
- 端到端(run_eval.py):**跑真模型**,采集工具轨迹 + LLM 判官打分,衡量"用户是否真拿到对的结果"。

标注集统一在 dataset.py。改 prompt / 换模型 / 调 route_line 关键词时:
先跑组件级定位是哪层坏,再跑端到端拍板要不要上。
"""
