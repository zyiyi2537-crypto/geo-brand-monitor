import { useTranslation } from 'react-i18next';
import { PageHead } from '../components/PageHead';

export function PrivacyPolicy() {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';

  return (
    <div className="min-h-screen grid-background relative">
      <PageHead titleKey="pageMeta.privacy.title" descriptionKey="pageMeta.privacy.description" />
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="text-3xl font-bold text-primary mb-8">
          {isZh ? '隐私政策' : 'Privacy Policy'}
        </h1>
        <p className="text-sm text-secondary mb-8">
          {isZh ? '最后更新：2026 年 4 月 16 日' : 'Last updated: April 16, 2026'}
        </p>
        <div className="prose prose-sm max-w-none text-secondary space-y-6">
          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '1. 概述' : '1. Overview'}
            </h2>
            <p>
              {isZh
                ? 'Vigilath（由 Zen7 运营，以下简称"我们"）重视您的隐私。本隐私政策说明我们在您使用 Vigilath GEO Readiness Checker（以下简称"服务"）时如何收集、使用和保护您的个人信息。'
                : 'Vigilath (operated by Zen7, hereinafter "we", "us", or "our") values your privacy. This Privacy Policy explains how we collect, use, and protect your personal information when you use the Vigilath GEO Readiness Checker (the "Service").'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '2. 我们收集的信息' : '2. Information We Collect'}
            </h2>
            <p className="font-medium text-primary">{isZh ? '账户信息' : 'Account Information'}</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '注册时提供的邮箱地址' : 'Email address provided during registration'}</li>
              <li>{isZh ? '密码（以加密哈希形式存储，我们无法访问原始密码）' : 'Password (stored as a cryptographic hash; we cannot access your raw password)'}</li>
            </ul>
            <p className="font-medium text-primary mt-3">{isZh ? '支付信息' : 'Payment Information'}</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '支付通过 Stripe 处理。我们不存储您的信用卡号。Stripe 可能收集账单地址和卡片后四位。' : 'Payments are processed by Stripe. We do not store your credit card number. Stripe may collect your billing address and last four digits of your card.'}</li>
            </ul>
            <p className="font-medium text-primary mt-3">{isZh ? '使用数据' : 'Usage Data'}</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '您提交检测的 URL' : 'URLs you submit for GEO checks'}</li>
              <li>{isZh ? '检测结果和评分' : 'Check results and scores'}</li>
              <li>{isZh ? '服务使用频率和配额' : 'Service usage frequency and quota'}</li>
            </ul>
            <p className="font-medium text-primary mt-3">{isZh ? '自动收集的信息' : 'Automatically Collected Information'}</p>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '语言偏好（通过 localStorage 存储）' : 'Language preference (stored via localStorage)'}</li>
              <li>{isZh ? 'IP 地址和基本请求日志（由 Cloudflare 和 Nginx 记录）' : 'IP address and basic request logs (recorded by Cloudflare and Nginx)'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '3. 信息使用方式' : '3. How We Use Your Information'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '提供和维护服务' : 'To provide and maintain the Service'}</li>
              <li>{isZh ? '处理支付和管理会员' : 'To process payments and manage memberships'}</li>
              <li>{isZh ? '发送支付收据（通过 Stripe）' : 'To send payment receipts (via Stripe)'}</li>
              <li>{isZh ? '改善服务体验' : 'To improve the Service experience'}</li>
              <li>{isZh ? '回复您的咨询' : 'To respond to your inquiries'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '4. 第三方服务' : '4. Third-Party Services'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>Stripe</strong> — {isZh ? '支付处理。受 Stripe 隐私政策约束。' : 'Payment processing. Subject to Stripe\'s Privacy Policy.'}</li>
              <li><strong>Cloudflare</strong> — {isZh ? 'CDN 和安全防护。可能收集 IP 地址和请求元数据。' : 'CDN and security. May collect IP addresses and request metadata.'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '5. 数据保留' : '5. Data Retention'}
            </h2>
            <p>
              {isZh
                ? '我们在您保持账户活跃期间保留您的数据。您可以随时请求删除账户和相关数据。'
                : 'We retain your data for as long as your account remains active. You may request deletion of your account and associated data at any time.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '6. 您的权利' : '6. Your Rights'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '访问我们持有的您的个人数据' : 'Access the personal data we hold about you'}</li>
              <li>{isZh ? '请求更正不准确的数据' : 'Request correction of inaccurate data'}</li>
              <li>{isZh ? '请求删除您的账户和数据' : 'Request deletion of your account and data'}</li>
              <li>{isZh ? '导出您的检测记录' : 'Export your detection records'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '7. 安全措施' : '7. Security'}
            </h2>
            <p>
              {isZh
                ? '我们采用行业标准的安全措施保护您的数据，包括 HTTPS 加密传输、密码哈希存储、Cloudflare WAF 防护。但请注意，互联网传输不能保证 100% 安全。'
                : 'We use industry-standard security measures to protect your data, including HTTPS encryption, password hashing, and Cloudflare WAF protection. However, no method of internet transmission is 100% secure.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '8. 联系我们' : '8. Contact Us'}
            </h2>
            <p>
              {isZh
                ? '如对本隐私政策有任何疑问，请联系我们：'
                : 'If you have questions about this Privacy Policy, please contact us:'}
            </p>
            <p className="mt-2">
              Email: <a href="mailto:support@zen7.com" className="text-accent-primary hover:underline">support@zen7.com</a>
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
