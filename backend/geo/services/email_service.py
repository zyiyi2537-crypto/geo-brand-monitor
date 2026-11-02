"""Resend transactional email client.

All outgoing mail (password reset, consultation acknowledgement, etc.) goes
through Resend's HTTP API. We talk to it with `requests` directly so no new
dependency is needed.

Secrets come from `backend/.env`:
    RESEND_API_KEY=re_xxx
    FROM_EMAIL="GEO Readiness Checker <noreply@vigilath.com>"
    FRONTEND_URL=https://www.vigilath.com
"""

import logging
from typing import Optional

import requests

from geo.database import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailService:
    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.FROM_EMAIL
        self.frontend_url = settings.FRONTEND_URL.rstrip("/")
        self.sales_notify_email = settings.SALES_NOTIFY_EMAIL

    def _send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> bool:
        if not self.api_key:
            logger.error("RESEND_API_KEY is not configured; cannot send email to %s", to)
            return False

        payload = {
            "from": self.from_email,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to

        try:
            resp = requests.post(
                RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
        except requests.RequestException as e:
            logger.exception("Resend request failed for %s: %s", to, e)
            return False

        if resp.status_code >= 400:
            logger.error(
                "Resend rejected message to %s (%s): %s",
                to,
                resp.status_code,
                resp.text,
            )
            return False

        logger.info("Resend accepted message to %s: %s", to, resp.json().get("id"))
        return True

    def send_password_reset_email(self, recipient_email: str, reset_token: str) -> bool:
        reset_link = f"{self.frontend_url}/forgot-password?token={reset_token}"

        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827;">Password Reset Request</h2>
            <p>Hello,</p>
            <p>You requested a password reset for your GEO Readiness Checker account. Click the button below to choose a new password:</p>
            <p>
              <a href="{reset_link}"
                 style="display: inline-block; background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600;">
                Reset Password
              </a>
            </p>
            <p>Or copy and paste this URL into your browser:</p>
            <p style="word-break: break-all; color: #4b5563;">{reset_link}</p>
            <p>This link will expire in 15 minutes. If you did not request a reset, you can safely ignore this email.</p>
            <p>— GEO Readiness Checker Team</p>
          </body>
        </html>
        """

        text = (
            "Password Reset Request\n\n"
            "You requested a password reset for your GEO Readiness Checker account.\n"
            f"Open this link to choose a new password: {reset_link}\n\n"
            "This link will expire in 15 minutes. If you did not request a reset, ignore this email.\n\n"
            "— GEO Readiness Checker Team"
        )

        return self._send(
            to=recipient_email,
            subject="Reset your GEO Readiness Checker password",
            html=html,
            text=text,
        )

    def send_consultation_confirmation_email(
        self, recipient_email: str, name: str, message: str
    ) -> bool:
        safe_message = (message or "").replace("\n", "<br>")

        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827;">Consultation Request Received</h2>
            <p>Hello {name},</p>
            <p>Thanks for reaching out to the GEO Readiness Checker team. We have received your consultation request and will get back to you shortly.</p>
            <p><strong>Your message:</strong></p>
            <blockquote style="margin: 0; padding: 12px 16px; background: #f3f4f6; border-left: 4px solid #2563eb;">
              {safe_message}
            </blockquote>
            <p>We appreciate your interest and will respond as soon as possible.</p>
            <p>— GEO Readiness Checker Team</p>
          </body>
        </html>
        """

        text = (
            f"Hello {name},\n\n"
            "Thanks for reaching out to the GEO Readiness Checker team. "
            "We have received your consultation request and will get back to you shortly.\n\n"
            "Your message:\n"
            f"{message}\n\n"
            "— GEO Readiness Checker Team"
        )

        return self._send(
            to=recipient_email,
            subject="We received your consultation request",
            html=html,
            text=text,
        )


    def send_sales_notification_email(
        self,
        *,
        kind: str,
        name: str,
        email: str,
        website: str,
        message: str,
        tier_slug: Optional[str] = None,
        submission_id: Optional[int] = None,
    ) -> bool:
        """Internal notification to ops/sales when a new consultation comes in.

        `reply_to` is set to the submitter so sales can hit "Reply" in their
        inbox and reach the customer directly, without copy-pasting.
        """
        safe_message = (message or "").replace("\n", "<br>") or "<em>(no message)</em>"
        kind_label = "Sales Lead" if kind == "sales-lead" else "Contact"
        subject_parts = [f"[{kind_label}"]
        if tier_slug:
            subject_parts.append(f" / {tier_slug}")
        subject_parts.append(f"] {name} <{email}>")
        subject = "".join(subject_parts)

        rows = [
            ("Type", kind_label),
            ("Name", name),
            ("Email", f'<a href="mailto:{email}">{email}</a>'),
            ("Website", f'<a href="{website}" rel="noopener">{website}</a>' if website else "—"),
        ]
        if tier_slug:
            rows.append(("Tier", tier_slug))
        rows.append(("Message", safe_message))
        if submission_id is not None:
            rows.append(("DB id", str(submission_id)))

        table_rows = "".join(
            f'<tr><td style="padding:6px 12px;color:#6b7280;vertical-align:top;white-space:nowrap;">{k}</td>'
            f'<td style="padding:6px 12px;color:#111827;">{v}</td></tr>'
            for k, v in rows
        )
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827; margin-bottom: 8px;">New {kind_label.lower()} submission</h2>
            <p style="color:#6b7280;margin-top:0;">Reply to this email to respond directly to the submitter.</p>
            <table style="border-collapse:collapse;border:1px solid #e5e7eb;">
              {table_rows}
            </table>
          </body>
        </html>
        """

        text_lines = [f"New {kind_label.lower()} submission", ""]
        for k, v in rows:
            # Strip HTML for the text fallback
            plain = v.replace("<br>", "\n").replace("<em>(no message)</em>", "(no message)")
            text_lines.append(f"{k}: {plain}")
        text_lines.append("")
        text_lines.append("Reply to this email to respond directly to the submitter.")

        return self._send(
            to=self.sales_notify_email,
            subject=subject,
            html=html,
            text="\n".join(text_lines),
            reply_to=email,
        )

    def send_review_result_email(
        self,
        *,
        to: str,
        topic_name: str,
        decision: str,                                  # 仅 "approved" — rejected 在去审核流里退役
        reject_reason: Optional[str] = None,            # 兼容签名,不再使用
        execution_plan_url: Optional[str] = None,
    ) -> bool:
        """去审核流 — 项目启动后给客户发通知(原审核通过邮件,改文案).

        decision != "approved" 直接 no-op(rejected 分支已退役).
        """
        del reject_reason  # 兼容旧调用方签名,不再使用
        if decision != "approved":
            return True

        subject = f"【GEO】您的 GEO 监测项目已启动:{topic_name}"
        cta_block = ""
        if execution_plan_url:
            cta_block = f"""
        <p>
          <a href="{execution_plan_url}"
             style="display: inline-block; background-color: #2563eb; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 600;">
            查看执行计划书
          </a>
        </p>
        <p style="word-break: break-all; color: #4b5563;">{execution_plan_url}</p>
        """
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827;">您的 GEO 监测项目已启动</h2>
            <p>主题:<strong>{topic_name}</strong></p>
            <p>我们已经为您的监测问题触发了一次正式跑批,并生成了执行计划书(含项目总体状况、主题日志、泛化日志和运行进度)。</p>
            {cta_block}
            <p>内容文案稿正在异步生成,生成完成后会在「文案复审」环节再次通知您。</p>
            <p>— GEO 团队</p>
          </body>
        </html>
        """
        text_lines = [
            "您的 GEO 监测项目已启动",
            f"主题:{topic_name}",
            "",
            "我们已经为您的监测问题触发了一次正式跑批,并生成了执行计划书。",
        ]
        if execution_plan_url:
            text_lines.append(f"查看执行计划书:{execution_plan_url}")
        text_lines += ["", "— GEO 团队"]
        return self._send(to=to, subject=subject, html=html, text="\n".join(text_lines))

    def send_content_review_result_email(
        self,
        *,
        to: str,
        doc_title: str,
        decision: str,                                  # "approved" | "rejected" | "published"
        reject_reason: Optional[str] = None,
        publish_targets: Optional[list[dict]] = None,
    ) -> bool:
        """Phase D — 内容文档审核结果通知(approved / rejected / published)."""
        if decision == "approved":
            subject = f"【GEO】内容审核通过:{doc_title}"
            body_title = "你的内容稿件已通过审核"
            extra = "<p>等待运营选定发布平台与媒体后,稿件会进入「已发布」状态。</p>"
        elif decision == "published":
            targets_html = ""
            if publish_targets:
                chips = "".join(
                    f'<span style="display:inline-block;padding:4px 10px;margin:2px 4px 2px 0;'
                    f'background:#eff6ff;color:#1d4ed8;border-radius:9999px;font-size:12px;">'
                    f'{(t.get("platform") or "")} {(t.get("media") or "")}</span>'
                    for t in publish_targets if isinstance(t, dict)
                )
                targets_html = f"<p><strong>发布去向:</strong></p><div>{chips}</div>"
            subject = f"【GEO】内容已发布:{doc_title}"
            body_title = "你的内容稿件已被标记为发布"
            extra = targets_html
        else:
            subject = f"【GEO】内容审核未通过:{doc_title}"
            body_title = "你的内容稿件未通过审核"
            extra = (
                f'<p><strong>未通过原因:</strong></p>'
                f'<blockquote style="margin:0;padding:12px 16px;background:#f3f4f6;border-left:4px solid #ef4444;">{reject_reason}</blockquote>'
                if reject_reason else ""
            )
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827;">{body_title}</h2>
            <p>稿件标题:<strong>{doc_title}</strong></p>
            {extra}
            <p>— GEO 团队</p>
          </body>
        </html>
        """
        text_lines = [body_title, f"稿件标题:{doc_title}", ""]
        if decision == "rejected" and reject_reason:
            text_lines.append(f"未通过原因:{reject_reason}")
        if decision == "published" and publish_targets:
            text_lines.append("发布去向:")
            for t in publish_targets:
                if isinstance(t, dict):
                    text_lines.append(f"  - {t.get('platform', '')} {t.get('media', '')}".rstrip())
        text_lines += ["", "— GEO 团队"]
        return self._send(to=to, subject=subject, html=html, text="\n".join(text_lines))

    def send_sales_lead_confirmation_email(
        self, recipient_email: str, name: str, tier_slug: Optional[str] = None
    ) -> bool:
        """Acknowledgement to the /contact-sales submitter, mirroring the one
        /contact already sends. Keeps both entry points consistent."""
        tier_line = (
            f"<p>Plan of interest: <strong>{tier_slug}</strong></p>" if tier_slug else ""
        )
        html = f"""
        <html>
          <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
            <h2 style="color: #111827;">We received your sales enquiry</h2>
            <p>Hello {name},</p>
            <p>Thanks for reaching out to Vigilath sales. We have received your enquiry and a team member will reply within 1 business day.</p>
            {tier_line}
            <p>— Vigilath Sales Team</p>
          </body>
        </html>
        """

        text = (
            f"Hello {name},\n\n"
            "Thanks for reaching out to Vigilath sales. We have received your enquiry "
            "and a team member will reply within 1 business day.\n"
        )
        if tier_slug:
            text += f"\nPlan of interest: {tier_slug}\n"
        text += "\n— Vigilath Sales Team"

        return self._send(
            to=recipient_email,
            subject="We received your Vigilath sales enquiry",
            html=html,
            text=text,
        )


email_service = EmailService()
