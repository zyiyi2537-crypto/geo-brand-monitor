import { useTranslation } from 'react-i18next';
import { PageHead } from '../components/PageHead';

export function CookiePolicy() {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';

  return (
    <div className="min-h-screen grid-background relative">
      <PageHead titleKey="pageMeta.cookie.title" descriptionKey="pageMeta.cookie.description" />
      <div className="max-w-3xl mx-auto px-6 py-16">
        <h1 className="text-3xl font-bold text-primary mb-8">
          {isZh ? 'Cookie 政策' : 'Cookie Policy'}
        </h1>
        <p className="text-sm text-secondary mb-8">
          {isZh ? '最后更新：2026 年 4 月 16 日' : 'Last updated: April 16, 2026'}
        </p>
        <div className="prose prose-sm max-w-none text-secondary space-y-6">
          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '1. 什么是 Cookie' : '1. What Are Cookies'}
            </h2>
            <p>
              {isZh
                ? 'Cookie 是网站存储在您设备上的小型文本文件，用于记住您的偏好和改善使用体验。我们也使用 localStorage 等浏览器存储技术。'
                : 'Cookies are small text files stored on your device by websites to remember preferences and improve your experience. We also use browser storage technologies such as localStorage.'}
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '2. 我们使用的 Cookie 和存储' : '2. Cookies & Storage We Use'}
            </h2>

            <p className="font-medium text-primary">{isZh ? '必要性存储' : 'Essential Storage'}</p>
            <div className="overflow-x-auto mt-2">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left" style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <th className="py-2 pr-4 font-medium text-primary">{isZh ? '名称' : 'Name'}</th>
                    <th className="py-2 pr-4 font-medium text-primary">{isZh ? '用途' : 'Purpose'}</th>
                    <th className="py-2 font-medium text-primary">{isZh ? '类型' : 'Type'}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><code>token</code></td>
                    <td className="py-2 pr-4">{isZh ? '登录认证令牌' : 'Authentication token'}</td>
                    <td className="py-2">localStorage</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><code>user</code></td>
                    <td className="py-2 pr-4">{isZh ? '当前用户基本信息' : 'Current user basic info'}</td>
                    <td className="py-2">localStorage</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><code>i18nextLng</code></td>
                    <td className="py-2 pr-4">{isZh ? '语言偏好（中文/英文）' : 'Language preference (zh/en)'}</td>
                    <td className="py-2">localStorage</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><code>theme</code></td>
                    <td className="py-2 pr-4">{isZh ? '主题偏好（浅色/深色）' : 'Theme preference (light/dark)'}</td>
                    <td className="py-2">localStorage</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <p className="font-medium text-primary mt-4">{isZh ? '第三方 Cookie' : 'Third-Party Cookies'}</p>
            <div className="overflow-x-auto mt-2">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left" style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <th className="py-2 pr-4 font-medium text-primary">{isZh ? '来源' : 'Source'}</th>
                    <th className="py-2 pr-4 font-medium text-primary">{isZh ? '用途' : 'Purpose'}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><strong>Stripe</strong></td>
                    <td className="py-2 pr-4">{isZh ? '在支付 checkout 页面使用，用于欺诈检测和支付处理' : 'Used on the payment checkout page for fraud detection and payment processing'}</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-2 pr-4"><strong>Cloudflare</strong></td>
                    <td className="py-2 pr-4">{isZh ? '安全防护和性能优化（如 __cf_bm 用于机器人检测）' : 'Security and performance (e.g., __cf_bm for bot detection)'}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '3. 如何管理 Cookie' : '3. How to Manage Cookies'}
            </h2>
            <p>
              {isZh
                ? '您可以通过浏览器设置管理或删除 Cookie 和 localStorage 数据。请注意，禁用必要性存储可能导致您需要重新登录或无法正常使用部分功能。'
                : 'You can manage or delete cookies and localStorage data through your browser settings. Please note that disabling essential storage may require you to log in again or prevent some features from working properly.'}
            </p>
            <ul className="list-disc pl-5 space-y-1 mt-2">
              <li><strong>Chrome</strong>: {isZh ? '设置 → 隐私与安全 → Cookie' : 'Settings → Privacy and Security → Cookies'}</li>
              <li><strong>Firefox</strong>: {isZh ? '设置 → 隐私与安全 → Cookie 和网站数据' : 'Settings → Privacy & Security → Cookies and Site Data'}</li>
              <li><strong>Safari</strong>: {isZh ? '偏好设置 → 隐私' : 'Preferences → Privacy'}</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-primary">
              {isZh ? '4. 联系我们' : '4. Contact Us'}
            </h2>
            <p>
              {isZh
                ? '如对本 Cookie 政策有任何疑问，请联系我们：'
                : 'If you have questions about this Cookie Policy, please contact us:'}
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
