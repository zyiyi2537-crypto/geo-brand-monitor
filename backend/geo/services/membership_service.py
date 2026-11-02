from typing import Optional, List
from datetime import datetime, timedelta
from geo.models.membership import (
    Membership,
    MembershipCreate,
    UserMembership,
    UserMembershipCreate,
    MembershipORM,
    UserMembershipORM,
)
from geo.database import SessionLocal
import json


# Must match the section-header labels printed by geo_checker (these are also
# the strings that show up in `GeoTestResult.checks[].category`, so the
# frontend can compare them 1:1).
FREE_CHECK_CATEGORIES = [
    "HTTPS",
    "robots.txt",
    "sitemap.xml",
    "Meta Tags",
    "Mobile-Friendliness & Page Weight",
]

ALL_CHECK_CATEGORIES = [
    "HTTPS",
    "robots.txt",
    "llms.txt",
    ".well-known Discovery",
    "sitemap.xml",
    "Search Engine & AI Platform Registration",
    "Structured Data",
    "Meta Tags",
    "Content Accessibility",
    "AI Crawl Readiness",
    "Content Quality for AI",
    "Technical Crawlability",
    "Authority & Trust Signals",
    "AI-Specific Optimization",
    "Social Signals",
    "AI Answer Format Optimization",
    "Schema Breadcrumbs & Knowledge Panel",
    "Mobile-Friendliness & Page Weight",
    "URL Normalization",
    "Outbound Links & Media",
    "Multilingual Content Depth",
    "Cross-Platform Content Distribution",
    "Multi-Page Sampling",
]


STARTER_FEATURES = {
    "basic_geo_coverage": "基础 GEO 覆盖",
    "llm_inclusion_spec": "完成 OpenAI / Gemini / Anthropic 收录规范",
    "copywriting": "网站文案全面建设和优化，使内容符合大模型抓取规则",
    "product_info_compliance": "品牌、产品名、描述在 LLM 中一致呈现",
    "continuous_maintenance": "项目周期内随大模型规则变化进行调整",
    "paid_ranking_seo": None,
    "reputation_mgmt": None,
    "pr_support": None,
    "delivery_cadence": "一次性项目交付",
}

GROWTH_FEATURES = {
    "basic_geo_coverage": "基础 GEO 覆盖",
    "llm_inclusion_spec": "适配 OpenAI / Gemini / Anthropic 收录规范",
    "copywriting": "含核心产品使用场景信息合规配置",
    "product_info_compliance": "使用场景级合规配置",
    "continuous_maintenance": "项目周期内",
    "paid_ranking_seo": "在排名类网站采购低成本投放位",
    "reputation_mgmt": None,
    "pr_support": None,
    "delivery_cadence": "一次性项目交付 + 榜单期发布",
}

SCALE_FEATURES = {
    "basic_geo_coverage": "全渠道定制化覆盖",
    "llm_inclusion_spec": "全渠道海外大模型 GEO 收录规则（不限于三大主流）",
    "copywriting": "定制化完成交易产品核心使用场景",
    "product_info_compliance": "定制化 + 信息校验 + 持续维护",
    "continuous_maintenance": "长期持续维护",
    "paid_ranking_seo": "监测排名类网站投放成本，确定性价比最高的预算",
    "reputation_mgmt": "每月撰写并发布 3–5 篇最佳榜单类文章，配套数据类文章、反向链接、验证页面支持",
    "pr_support": "可配合企业内部团队或专属公关机构，助力获得媒体报道",
    "delivery_cadence": "月度持续输出（非一次性）",
}


DEFAULT_MEMBERSHIPS = [
    {
        "slug": "free",
        "name": "注册会员",
        "price": 0.0,
        "period": "/月",
        "description": "注册即可体验完整 23 类 GEO 检测，适合个人用户初步尝鲜",
        "popular": False,
        "tier_type": "saas",
        "currency": "usd",
        "monthly_check_quota": 3,
        "allowed_check_categories": None,  # 全部 23 项
        "display_order": 1,
        "features": [
            "注册即可使用",
            "23 项完整检测（全部子项）",
            "每月 3 次检测",
            "AI Visibility Score + 字母等级 + 可视化",
            "即时结果展示",
        ],
        "not_included": [
            "优化建议详细度",
            "检测项优先级排序",
            "检测历史记录",
            "技术支持",
        ],
        "features_json": None,
    },
    {
        "slug": "pro",
        "name": "检测会员",
        "price": 9.99,
        "period": "/月",
        "description": "需要完整自助检测结果的网站管理员和个人开发者",
        "popular": True,
        "tier_type": "saas",
        "currency": "usd",
        "monthly_check_quota": 20,
        "allowed_check_categories": None,  # 全部 23 项
        "display_order": 2,
        "features": [
            "需登录账号",
            "23 项完整检测（全部子项）",
            "每月 20 次检测",
            "检测项优先级排序",
            "完整 23 类报告（AI Visibility Score + 字母等级 + 可视化）",
            "检测历史记录（可回看）",
            "基础技术支持（工单 / 邮件）",
        ],
        "not_included": [
            "人工优化方案交付",
            "海外 LLM 收录规范",
            "榜单投放与声誉管理",
            "PR 支持",
        ],
        "features_json": None,
    },
    {
        "slug": "starter",
        "name": "Starter",
        "price": 999.0,
        "period": "/月",
        "description": "初阶团队的无限检测与优化建议",
        "popular": False,
        "tier_type": "saas",
        "currency": "usd",
        "monthly_check_quota": 0,  # 无限
        "allowed_check_categories": None,
        "display_order": 3,
        "features": [
            "无限检测次数",
            "23 项完整检测 + 详细优化建议",
            "基础 GEO 覆盖",
            "OpenAI / Gemini / Anthropic 收录规范",
            "网站文案建设与优化",
            "核心产品信息合规配置",
            "项目周期内持续维护",
        ],
        "not_included": [
            "付费榜单 SEO 投放",
            "声誉管理",
            "PR 支持",
        ],
        "features_json": {
            **STARTER_FEATURES,
            "delivery_form": "SaaS 订阅，按月续费",
        },
    },
    {
        "slug": "growth",
        "name": "Growth",
        "price": 2500.0,
        "period": "/月",
        "description": "增长期品牌的无限检测 + 优化建议 + 榜单投放",
        "popular": False,
        "tier_type": "saas",
        "currency": "usd",
        "monthly_check_quota": 0,  # 无限
        "allowed_check_categories": None,
        "display_order": 4,
        "features": [
            "无限检测次数",
            "23 项完整检测 + 详细优化建议",
            "海外主流 LLM 收录规范适配",
            "含使用场景级文案与合规配置",
            "付费榜单 SEO 低成本投放位",
            "优先技术支持（< 24h 响应）",
            "按月持续交付",
        ],
        "not_included": [
            "声誉管理（仅 Scale 才有）",
            "PR 支持",
        ],
        "features_json": {
            **GROWTH_FEATURES,
            "delivery_form": "SaaS 订阅，按月续费",
        },
    },
    {
        "slug": "scale",
        "name": "Scale",
        "price": 0.0,
        "period": "",
        "description": "大型企业的全渠道 GEO 解决方案 + PR（联系销售定制）",
        "popular": False,
        "tier_type": "service",
        "currency": "usd",
        "monthly_check_quota": 0,  # 无限
        "allowed_check_categories": None,
        "display_order": 5,
        "features": [
            "无限检测次数 + 详细优化建议",
            "全渠道定制化 GEO 覆盖",
            "全渠道海外 LLM 收录规则",
            "声誉管理：每月 3–5 篇榜单文章 + 反向链接",
            "PR 支持（媒体报道对接）",
            "24/7 + 专属顾问对接",
            "月度持续输出",
        ],
        "not_included": [],
        "features_json": {
            **SCALE_FEATURES,
            "price_range_usd": "Get a Demo",
            "delivery_form": "定制企业服务，联系销售",
        },
    },
]


def _orm_to_model(db_membership: MembershipORM) -> Membership:
    allowed = db_membership.allowed_check_categories
    features_json_raw = db_membership.features_json
    return Membership(
        id=db_membership.id,
        slug=db_membership.slug,
        name=db_membership.name,
        price=db_membership.price,
        currency=(db_membership.currency or "usd").lower(),
        period=db_membership.period,
        description=db_membership.description,
        popular=db_membership.popular,
        features=json.loads(db_membership.features) if db_membership.features else [],
        not_included=json.loads(db_membership.not_included) if db_membership.not_included else [],
        tier_type=db_membership.tier_type or "saas",
        monthly_check_quota=db_membership.monthly_check_quota or 0,
        allowed_check_categories=json.loads(allowed) if allowed else None,
        features_json=json.loads(features_json_raw) if features_json_raw else None,
        display_order=db_membership.display_order or 0,
        created_at=db_membership.created_at,
        updated_at=db_membership.updated_at,
    )


def _seed_membership(db, data: dict) -> MembershipORM:
    db_membership = MembershipORM(
        slug=data["slug"],
        name=data["name"],
        price=data["price"],
        currency=data.get("currency", "usd"),
        period=data["period"],
        description=data["description"],
        popular=data["popular"],
        features=json.dumps(data["features"], ensure_ascii=False),
        not_included=json.dumps(data["not_included"], ensure_ascii=False),
        tier_type=data["tier_type"],
        monthly_check_quota=data["monthly_check_quota"],
        allowed_check_categories=(
            json.dumps(data["allowed_check_categories"], ensure_ascii=False)
            if data.get("allowed_check_categories") is not None
            else None
        ),
        features_json=(
            json.dumps(data["features_json"], ensure_ascii=False)
            if data.get("features_json") is not None
            else None
        ),
        display_order=data["display_order"],
    )
    db.add(db_membership)
    return db_membership


class MembershipService:
    def __init__(self):
        self._initialize_default_memberships()

    def _initialize_default_memberships(self):
        """Seed 5-tier default memberships if table is empty."""
        db = SessionLocal()
        try:
            if db.query(MembershipORM).count() > 0:
                return
            for data in DEFAULT_MEMBERSHIPS:
                _seed_membership(db, data)
            db.commit()
        finally:
            db.close()

    def reseed_memberships(self):
        """Destructive: wipe memberships + user_memberships + reseed.
        Used by the migration script."""
        db = SessionLocal()
        try:
            db.query(UserMembershipORM).delete()
            db.query(MembershipORM).delete()
            db.commit()
            for data in DEFAULT_MEMBERSHIPS:
                _seed_membership(db, data)
            db.commit()
        finally:
            db.close()

    def create_membership(self, membership: MembershipCreate) -> Membership:
        db = SessionLocal()
        try:
            db_membership = MembershipORM(
                slug=membership.slug,
                name=membership.name,
                price=membership.price,
                currency=membership.currency,
                period=membership.period,
                description=membership.description,
                popular=membership.popular,
                features=json.dumps(membership.features, ensure_ascii=False),
                not_included=json.dumps(membership.not_included, ensure_ascii=False),
                tier_type=membership.tier_type,
                monthly_check_quota=membership.monthly_check_quota,
                allowed_check_categories=(
                    json.dumps(membership.allowed_check_categories, ensure_ascii=False)
                    if membership.allowed_check_categories is not None
                    else None
                ),
                features_json=(
                    json.dumps(membership.features_json, ensure_ascii=False)
                    if membership.features_json is not None
                    else None
                ),
                display_order=membership.display_order,
            )
            db.add(db_membership)
            db.commit()
            db.refresh(db_membership)
            return _orm_to_model(db_membership)
        finally:
            db.close()

    def get_membership_by_id(self, membership_id: int) -> Optional[Membership]:
        db = SessionLocal()
        try:
            db_membership = db.query(MembershipORM).filter(MembershipORM.id == membership_id).first()
            return _orm_to_model(db_membership) if db_membership else None
        finally:
            db.close()

    def get_membership_by_slug(self, slug: str) -> Optional[Membership]:
        db = SessionLocal()
        try:
            db_membership = db.query(MembershipORM).filter(MembershipORM.slug == slug).first()
            return _orm_to_model(db_membership) if db_membership else None
        finally:
            db.close()

    def get_all_memberships(self) -> List[Membership]:
        db = SessionLocal()
        try:
            db_memberships = (
                db.query(MembershipORM).order_by(MembershipORM.display_order.asc()).all()
            )
            return [_orm_to_model(m) for m in db_memberships]
        finally:
            db.close()

    def update_membership(
        self, membership_id: int, membership_update: MembershipCreate
    ) -> Optional[Membership]:
        db = SessionLocal()
        try:
            db_membership = db.query(MembershipORM).filter(MembershipORM.id == membership_id).first()
            if not db_membership:
                return None
            db_membership.slug = membership_update.slug
            db_membership.name = membership_update.name
            db_membership.price = membership_update.price
            db_membership.currency = membership_update.currency
            db_membership.period = membership_update.period
            db_membership.description = membership_update.description
            db_membership.popular = membership_update.popular
            db_membership.features = json.dumps(membership_update.features, ensure_ascii=False)
            db_membership.not_included = json.dumps(membership_update.not_included, ensure_ascii=False)
            db_membership.tier_type = membership_update.tier_type
            db_membership.monthly_check_quota = membership_update.monthly_check_quota
            db_membership.allowed_check_categories = (
                json.dumps(membership_update.allowed_check_categories, ensure_ascii=False)
                if membership_update.allowed_check_categories is not None
                else None
            )
            db_membership.features_json = (
                json.dumps(membership_update.features_json, ensure_ascii=False)
                if membership_update.features_json is not None
                else None
            )
            db_membership.display_order = membership_update.display_order
            db.commit()
            db.refresh(db_membership)
            return _orm_to_model(db_membership)
        finally:
            db.close()

    def delete_membership(self, membership_id: int) -> bool:
        db = SessionLocal()
        try:
            db_membership = db.query(MembershipORM).filter(MembershipORM.id == membership_id).first()
            if not db_membership:
                return False
            db.delete(db_membership)
            db.commit()
            return True
        finally:
            db.close()

    def create_user_membership(self, user_membership: UserMembershipCreate) -> UserMembership:
        db = SessionLocal()
        try:
            db_user_membership = UserMembershipORM(
                user_id=user_membership.user_id,
                membership_id=user_membership.membership_id,
                start_date=user_membership.start_date,
                end_date=user_membership.end_date,
                is_active=True,
            )
            db.add(db_user_membership)
            db.commit()
            db.refresh(db_user_membership)
            return UserMembership(
                id=db_user_membership.id,
                user_id=db_user_membership.user_id,
                membership_id=db_user_membership.membership_id,
                start_date=db_user_membership.start_date,
                end_date=db_user_membership.end_date,
                is_active=db_user_membership.is_active,
            )
        finally:
            db.close()

    def get_user_membership(self, user_id: int) -> Optional[UserMembership]:
        db = SessionLocal()
        try:
            db_user_membership = (
                db.query(UserMembershipORM)
                .filter(UserMembershipORM.user_id == user_id, UserMembershipORM.is_active == True)
                .first()
            )
            if not db_user_membership:
                return None
            if datetime.utcnow() < db_user_membership.end_date:
                return UserMembership(
                    id=db_user_membership.id,
                    user_id=db_user_membership.user_id,
                    membership_id=db_user_membership.membership_id,
                    start_date=db_user_membership.start_date,
                    end_date=db_user_membership.end_date,
                    is_active=db_user_membership.is_active,
                )
            db_user_membership.is_active = False
            db.commit()
            return None
        finally:
            db.close()

    def get_effective_membership(self, user_id: int) -> Membership:
        """Return user's active paid membership, or fall back to the free tier."""
        user_membership = self.get_user_membership(user_id)
        if user_membership:
            membership = self.get_membership_by_id(user_membership.membership_id)
            if membership:
                return membership
        free = self.get_membership_by_slug("free")
        if free is None:
            raise RuntimeError("Free membership tier not initialized")
        return free

    def upgrade_membership(self, user_id: int, new_membership_id: int) -> Optional[UserMembership]:
        db = SessionLocal()
        try:
            current_membership = (
                db.query(UserMembershipORM)
                .filter(UserMembershipORM.user_id == user_id, UserMembershipORM.is_active == True)
                .first()
            )
            if current_membership:
                current_membership.is_active = False
                db.commit()

            new_membership = (
                db.query(MembershipORM).filter(MembershipORM.id == new_membership_id).first()
            )
            if not new_membership:
                return None

            now = datetime.utcnow()
            period = new_membership.period or ""
            if "/月" in period or "/mo" in period.lower():
                duration = timedelta(days=30)
            elif "/年" in period or "/yr" in period.lower() or "/year" in period.lower():
                duration = timedelta(days=365)
            else:
                duration = timedelta(days=36500)

            # Renewing the same plan: extend from the old end_date if still active
            if (
                current_membership
                and current_membership.membership_id == new_membership_id
                and current_membership.end_date
                and current_membership.end_date > now
            ):
                start_date = now
                end_date = current_membership.end_date + duration
            else:
                start_date = now
                end_date = now + duration

            db_user_membership = UserMembershipORM(
                user_id=user_id,
                membership_id=new_membership_id,
                start_date=start_date,
                end_date=end_date,
                is_active=True,
            )
            db.add(db_user_membership)
            db.commit()
            db.refresh(db_user_membership)
            return UserMembership(
                id=db_user_membership.id,
                user_id=db_user_membership.user_id,
                membership_id=db_user_membership.membership_id,
                start_date=db_user_membership.start_date,
                end_date=db_user_membership.end_date,
                is_active=db_user_membership.is_active,
            )
        finally:
            db.close()

    def cancel_membership(self, user_id: int) -> bool:
        db = SessionLocal()
        try:
            user_membership = (
                db.query(UserMembershipORM)
                .filter(UserMembershipORM.user_id == user_id, UserMembershipORM.is_active == True)
                .first()
            )
            if user_membership:
                user_membership.is_active = False
                db.commit()
                return True
            return False
        finally:
            db.close()


membership_service = MembershipService()
