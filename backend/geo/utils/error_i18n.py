"""Backend error message localization.

The global exception handler (in `error_handler.py`) inspects the incoming
`Accept-Language` header and runs every outgoing error message through
`localize()` below. Messages raised anywhere in the API stay in canonical
English; this module is the single place we map them to zh-CN.

There are two lookup paths:

1. **Direct table** — literal English strings → per-language strings. Use this
   for error messages that have no runtime parameters.
2. **Pattern table** — regex with capture groups → per-language format strings.
   Use this for messages that embed runtime data (quota used/total, mode names,
   tier names, etc.). The regex runs on the full English message and the
   captured groups are positionally substituted into the localized template.

When nothing matches, the original English message is returned unchanged, so
adding a new raise site never breaks the error path — it just won't be
localized until someone adds an entry here.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple


# --- Literal-match table -------------------------------------------------

# Keyed by the exact English string raised in the codebase. Only keys that
# currently appear in `grep -rn "raise AppException" backend/geo` need entries.
MESSAGES: Dict[str, Dict[str, str]] = {
    # Validation / URL
    "Invalid URL format": {"zh": "URL 格式无效，请输入合法的网址"},
    "Unable to analyze this URL. Please check the address and try again.": {
        "zh": "无法分析该网址，请确认输入的地址正确且可访问后重试。"
    },

    # Auth
    "Email already registered": {"zh": "邮箱已被注册"},
    "Incorrect email or password": {"zh": "邮箱或密码错误"},
    "Could not validate credentials": {"zh": "登录凭证无效或已过期，请重新登录"},
    "Invalid or expired token": {"zh": "登录凭证无效或已过期，请重新登录"},
    "Email not found": {"zh": "该邮箱尚未注册"},
    "Invalid reset token": {"zh": "重置令牌无效或已过期"},
    "Failed to send password reset email": {"zh": "发送密码重置邮件失败，请稍后重试"},
    "User not found": {"zh": "用户不存在"},
    "Invalid Google token": {"zh": "Google 登录令牌无效"},
    "Invalid Google client ID": {"zh": "Google 客户端 ID 配置错误"},

    # Account / membership
    "Current password is incorrect": {"zh": "原密码错误"},
    "Detection record not found": {"zh": "检测记录不存在"},
    "Membership not found": {"zh": "会员套餐不存在"},
    "User membership not found": {"zh": "用户会员记录不存在"},
    "You can only create membership for yourself": {"zh": "只能为自己创建会员"},
    "New membership ID is required": {"zh": "必须提供新的会员 ID"},
    "Free membership tier not initialized": {
        "zh": "免费会员档位尚未初始化，请联系管理员"
    },
    "Free tier does not require payment": {"zh": "免费档位无需支付"},
    "This plan requires contacting sales, not self-serve": {
        "zh": "该套餐需联系销售开通，不支持自助订阅"
    },

    # Payment / Stripe
    "Stripe is not configured on this server (STRIPE_SECRET_KEY missing)": {
        "zh": "服务器尚未配置 Stripe 支付（缺少 STRIPE_SECRET_KEY）"
    },
    "Stripe webhook secret not configured": {"zh": "Stripe Webhook Secret 未配置"},
    "Missing Stripe signature header": {"zh": "缺少 Stripe 签名请求头"},
    "Invalid webhook payload": {"zh": "Webhook 载荷无效"},
    "Invalid webhook signature": {"zh": "Webhook 签名验证失败"},

    # Contact / email
    "Failed to send confirmation email": {"zh": "发送确认邮件失败，请稍后重试"},

    # Internal / system
    "Database error": {"zh": "数据库错误，请稍后重试"},
    "Internal server error": {"zh": "服务器内部错误，请稍后重试"},
    "Validation error": {"zh": "请求参数校验失败"},
    "anonymous quota called without client_id": {
        "zh": "匿名配额调用缺少客户端标识"
    },
}


# --- Parameterized pattern table ------------------------------------------

# Each entry is (compiled regex, {lang: format_template}). The regex must
# match the full English message (use ^...$). Capture groups are substituted
# positionally with `.format(*groups)` into the localized template.
PATTERNS: List[Tuple[re.Pattern[str], Dict[str, str]]] = [
    (
        re.compile(r"^Monthly check quota exceeded \((\d+)/(\d+)\)\. Upgrade to continue\.$"),
        {
            "zh": "本月检测次数已用完（{0}/{1}），请升级套餐后继续使用。",
        },
    ),
    (
        re.compile(
            r"^Anonymous monthly quota exceeded \((\d+)/(\d+)\)\. Please sign up or log in to continue\.$"
        ),
        {
            "zh": "未注册用户每月最多检测 {1} 次（{0}/{1}），请注册或登录后继续使用。",
        },
    ),
    (
        re.compile(r"^'(.+)' requires (.+) tier or higher$"),
        {
            "zh": "「{0}」功能需要 {1} 或更高档位",
        },
    ),
    (
        re.compile(r"^Membership '(.+)' not found$"),
        {
            "zh": "会员套餐「{0}」不存在",
        },
    ),
    (
        re.compile(r"^(.+) is a managed service — contact sales, not self-serve$"),
        {
            "zh": "「{0}」为人工服务档位，请联系销售人员购买",
        },
    ),
    (
        re.compile(r"^Stripe error: (.+)$"),
        {
            "zh": "Stripe 支付错误：{0}",
        },
    ),
    (
        re.compile(r"^advanced check failed: (.+)$"),
        {
            "zh": "高级检测失败：{0}",
        },
    ),
    (
        re.compile(r"^unknown mode (.+)$"),
        {
            "zh": "未知的高级检测模式：{0}",
        },
    ),
]


# --- Language negotiation --------------------------------------------------


def _normalize_lang(raw: str | None) -> str:
    """Collapse an Accept-Language value to a stable 2-letter key.

    The header can look like "zh-CN,zh;q=0.9,en;q=0.8" or just "en". We only
    care about the first tag and only map zh/en today — anything else falls
    through to "en" and gets the English source message.
    """
    if not raw:
        return "en"
    first = raw.split(",")[0].strip().lower()
    if not first:
        return "en"
    if first.startswith("zh"):
        return "zh"
    return first.split("-")[0] or "en"


def localize(message: str, lang: str | None) -> str:
    """Translate `message` into `lang` if a mapping exists; else return as-is.

    Callers should pass the raw `Accept-Language` header value (or already-
    normalized 2-letter code). Missing / unknown / English locales always
    return the input unchanged, so adding a language later only requires new
    dictionary entries.
    """
    key = _normalize_lang(lang)
    if key == "en":
        return message

    entry = MESSAGES.get(message)
    if entry and key in entry:
        return entry[key]

    for pattern, translations in PATTERNS:
        m = pattern.match(message)
        if m and key in translations:
            return translations[key].format(*m.groups())

    return message


# Exposed for tests / debugging.
def supported_languages() -> Iterable[str]:
    return ("en", "zh")
