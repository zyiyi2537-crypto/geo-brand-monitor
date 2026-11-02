import { useTranslation } from 'react-i18next';
import { PageHead } from '../components/PageHead';

export function TermsOfUse() {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';

  return (
    <div className="min-h-screen grid-background relative">
      <PageHead titleKey="pageMeta.terms.title" descriptionKey="pageMeta.terms.description" />
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="text-3xl font-bold text-primary mb-8">
          {isZh ? '使用条款' : 'Terms of Use'}
        </h1>
        <p className="text-sm text-secondary mb-8">
          {isZh ? '最后更新：2026 年 4 月 16 日' : 'Last updated: April 16, 2026'}
        </p>
        <div className="prose prose-sm max-w-none text-secondary space-y-6">
          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '1. 服务说明' : '1. Service Description'}
            </h2>
            <p>
              {isZh
                ? 'Vigilath GEO Readiness Checker（以下简称"服务"）由 Zen7 运营，提供网站生成式引擎优化（GEO）检测与分析服务。服务包括免费基础检测和付费会员高级功能。'
                : 'The Vigilath GEO Readiness Checker (the "Service") is operated by Zen7 and provides Generative Engine Optimization (GEO) detection and analysis for websites. The Service includes free basic checks and paid membership tiers with advanced features.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '2. 账户注册' : '2. Account Registration'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '您必须提供有效的邮箱地址注册账户' : 'You must provide a valid email address to register an account'}</li>
              <li>{isZh ? '您有责任保管好账户密码的安全' : 'You are responsible for maintaining the security of your account password'}</li>
              <li>{isZh ? '每人仅限注册一个账户' : 'Each person may only register one account'}</li>
              <li>{isZh ? '您必须年满 18 岁或达到所在司法管辖区的法定年龄' : 'You must be at least 18 years old or the legal age in your jurisdiction'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '3. 会员与支付' : '3. Membership & Payment'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '付费会员以月度周期计费（30 天）' : 'Paid memberships are billed in monthly cycles (30 days)'}</li>
              <li>{isZh ? '支付通过 Stripe 处理，以美元 (USD) 计价' : 'Payments are processed via Stripe and denominated in USD'}</li>
              <li>{isZh ? '会员权益在支付成功后立即生效' : 'Membership benefits activate immediately upon successful payment'}</li>
              <li>{isZh ? '续费同一方案时，未使用的天数将自动顺延' : 'When renewing the same plan, unused days are automatically carried forward'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '4. 退款政策' : '4. Refund Policy'}
            </h2>
            <p>
              {isZh
                ? '如因系统问题导致重复扣款，我们将全额退款。对于正常的会员购买，由于服务为即时交付的数字产品，原则上不支持退款。如有特殊情况，请联系 support@zen7.com。'
                : 'Duplicate charges caused by system errors will be fully refunded. For standard membership purchases, refunds are generally not available as the Service is an instantly delivered digital product. For special circumstances, please contact support@zen7.com.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '5. 可接受的使用' : '5. Acceptable Use'}
            </h2>
            <ul className="list-disc pl-5 space-y-1">
              <li>{isZh ? '不得滥用服务（如大量自动化请求、绕过配额限制）' : 'Do not abuse the Service (e.g., automated mass requests, circumventing quota limits)'}</li>
              <li>{isZh ? '不得将服务用于任何违法目的' : 'Do not use the Service for any illegal purpose'}</li>
              <li>{isZh ? '不得尝试未经授权访问其他用户的数据' : 'Do not attempt unauthorized access to other users\' data'}</li>
              <li>{isZh ? '不得干扰或破坏服务的正常运行' : 'Do not interfere with or disrupt the operation of the Service'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '6. 知识产权' : '6. Intellectual Property'}
            </h2>
            <p>
              {isZh
                ? '服务的所有内容、设计、代码和品牌标识均为 Zen7 的知识产权。检测报告中的分析结果供您个人或商业使用，但不得转售检测服务本身。'
                : 'All content, design, code, and branding of the Service are the intellectual property of Zen7. Analysis results in detection reports are licensed for your personal or commercial use, but you may not resell the detection service itself.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '7. 免责声明' : '7. Disclaimer'}
            </h2>
            <p>
              {isZh
                ? '服务按"现状"提供。GEO 检测结果仅供参考，不构成对搜索引擎排名或 AI 引擎推荐效果的保证。我们不对因使用检测结果而产生的任何直接或间接损失承担责任。'
                : 'The Service is provided "as is". GEO check results are for reference only and do not constitute a guarantee of search engine rankings or AI engine recommendation outcomes. We are not liable for any direct or indirect losses arising from the use of check results.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '8. 服务变更与终止' : '8. Changes & Termination'}
            </h2>
            <p>
              {isZh
                ? '我们保留随时修改、暂停或终止服务的权利。重大变更将提前通知。我们也保留因违反本条款而终止用户账户的权利。'
                : 'We reserve the right to modify, suspend, or terminate the Service at any time. Material changes will be communicated in advance. We also reserve the right to terminate user accounts for violation of these Terms.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '9. 联系我们' : '9. Contact Us'}
            </h2>
            <p>
              {isZh
                ? '如对本使用条款有任何疑问，请联系我们：'
                : 'If you have questions about these Terms, please contact us:'}
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
