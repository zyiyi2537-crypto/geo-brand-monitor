"""Agent 相关数据表(对话式 GEO 助手)。

agent_materials —— 用户上传的资料知识库(「知识库 = 用户信息」),供 ask_knowledge 检索
+ 后续诊断/产稿 grounding。MVP 用关键词检索,故先不带向量列(后续可加 embedding 列升级语义检索)。
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from geo.database import Base


class AgentMaterialORM(Base):
    __tablename__ = "agent_materials"
    __table_args__ = (Index("idx_agent_mat_acct_topic", "account_id", "topic_id"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)   # = 用户/账号,租户隔离
    topic_id = Column(Integer, nullable=True)                   # 可选关联主题
    source = Column(String(length=512), nullable=False, default="")   # url 或文件名
    title = Column(String(length=512), nullable=False, default="")
    text = Column(Text, nullable=False, default="")            # 解析后的纯文本
    embedding_json = Column(Text, nullable=True)               # 向量(JSON float 数组,DashScope);空=回退关键词
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentConversationORM(Base):
    """账号级多轮对话记忆(会话单位=账号↔助手)。messages_json 存 Pydantic AI 序列化的消息历史。"""
    __tablename__ = "agent_conversations"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, unique=True, index=True)  # 一账号一会话
    messages_json = Column(Text, nullable=False, default="[]")            # ModelMessagesTypeAdapter 序列化
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentTokenORM(Base):
    """对外开放的账号级 token(见 agent integration API)。

    1 年期 token,API-key 风格,给外部 agent(小龙虾)链接本 GEO agent 用。
    token 本身是签名 JWT(库里只存 tid + 元数据,不存明文);校验时**必查 enabled**(长期 token 吊销命门)。
    """
    __tablename__ = "agent_tokens"

    id = Column(Integer, primary_key=True, index=True)
    tid = Column(String(length=64), nullable=False, unique=True, index=True)   # token id = JWT 的 tid
    account_id = Column(Integer, nullable=False, index=True)                    # 这只小龙虾代表的账号
    caps = Column(String(length=128), nullable=False, default="read")          # 逗号分隔:read[,write]
    origins = Column(Text, nullable=False, default="")                         # 逗号分隔 CORS 白名单(浏览器直连才校验)
    label = Column(String(length=255), nullable=False, default="")             # 备注(发给谁)
    enabled = Column(Integer, nullable=False, default=1)                       # 0=吊销
    expires_at = Column(DateTime, nullable=False)                              # 默认 +1 年
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentIMConnectorORM(Base):
    """IM 接入器(自建应用模式)。客户在自己飞书/企微建自建应用,把 App 凭证粘到这里。

    一个自建应用 = 一个 Vigilath 账号:回调按 app_id 反查本表 → account_id,
    该应用下所有 IM 用户都以这个账号身份对话(数据隔离靠 account_id)。
    """
    __tablename__ = "agent_im_connectors"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(length=16), nullable=False)        # feishu / wecom
    app_id = Column(String(length=128), nullable=False, index=True)   # 飞书 App ID / 企微 CorpID
    app_secret = Column(String(length=256), nullable=False, default="")
    verify_token = Column(String(length=128), nullable=False, default="")   # 事件订阅 Verification Token / 企微 Token
    aes_key = Column(String(length=128), nullable=False, default="")        # 飞书 Encrypt Key / 企微 EncodingAESKey(空=不加密)
    config_json = Column(Text, nullable=False, default="{}")    # 平台特有(企微 agent_id 等)
    last_chat_id = Column(String(length=256), nullable=False, default="")  # 最近一次对话的会话/用户标识,主动推送回推用
    enabled = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentNotificationORM(Base):
    """主动通知(舆情高风险等)。Web 端打开聊天窗时拉未读;IM 端最佳努力回推。"""
    __tablename__ = "agent_notifications"
    __table_args__ = (Index("ix_agent_notif_acct", "account_id", "read_at"),)

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, nullable=False)
    title = Column(String(length=255), nullable=False, default="")
    body = Column(Text, nullable=False, default="")
    dedup_key = Column(String(length=128), nullable=False, unique=True, index=True)  # 去重:同事件不重复推
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)


class AgentIMUserBindingORM(Base):
    """IM 使用者 ↔ Vigilath 账号绑定(ISV 模式,每用户各自绑)。

    ISV 一个 app 服务无数企业,靠 (platform, tenant_key, open_id) 定位飞书用户 → account_id。
    """
    __tablename__ = "agent_im_user_bindings"
    __table_args__ = (Index("ix_agent_im_bind_lookup", "platform", "tenant_key", "open_id", unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(length=16), nullable=False)        # feishu / wecom
    tenant_key = Column(String(length=128), nullable=False, default="")   # 飞书企业标识(ISV)
    open_id = Column(String(length=128), nullable=False)        # 该用户在本 app 下的 open_id
    account_id = Column(Integer, nullable=False, index=True)     # 绑定到的 Vigilath 账号
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentIMBindCodeORM(Base):
    """一次性绑定码:控制台为登录账号生成,用户在 IM 发给机器人完成绑定。"""
    __tablename__ = "agent_im_bind_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(length=16), nullable=False, unique=True, index=True)
    account_id = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AgentISVStateORM(Base):
    """ISV 动态状态(主要存飞书定时推送的 app_ticket;换 app_access_token 必需)。"""
    __tablename__ = "agent_isv_state"

    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(length=128), nullable=False, unique=True, index=True)
    app_ticket = Column(String(length=256), nullable=False, default="")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
