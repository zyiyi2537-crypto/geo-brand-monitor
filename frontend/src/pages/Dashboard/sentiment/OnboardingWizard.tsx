import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { TagInput } from './components/TagInput';
import { isMockMode } from '../../../services/sentimentApi';
import { useCreateAccount } from '../../../hooks/useSentiment';

interface Props {
  onSubmit?: () => void;
}

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function OnboardingWizard({ onSubmit }: Props) {
  const { t } = useTranslation();
  const usingMock = isMockMode();
  const createAccount = useCreateAccount();

  const [target, setTarget] = useState('');
  const [ticker, setTicker] = useState('');
  const [intents, setIntents] = useState<string[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [emails, setEmails] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = target.trim().length > 0 && ticker.trim().length > 0;
  const submitting = createAccount.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || submitting) return;
    setError(null);

    if (usingMock) {
      // mock 模式:不调 API,直接通知父组件
      onSubmit?.();
      alert(t('dashboard.sentiment.onboarding.running'));
      return;
    }

    try {
      await createAccount.mutateAsync({
        target: target.trim(),
        ticker: ticker.trim(),
        intent: intents.length > 0 ? intents.join('、') : undefined,
        keywords,
        notify_emails: emails,
        run_now: true,
      });
      onSubmit?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-6 sm:py-10">
      <div className="text-center mb-8">
        <div className="text-5xl mb-3">📡</div>
        <h1 className="text-2xl sm:text-3xl font-bold text-primary mb-2">
          {t('dashboard.sentiment.onboarding.title')}
        </h1>
        <p className="text-secondary text-sm sm:text-base">
          {t('dashboard.sentiment.onboarding.subtitle')}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="rounded-xl p-6 space-y-5" style={cardStyle}>
        <Field label={t('dashboard.sentiment.onboarding.field.target')} required>
          <input
            type="text"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="世纪互联"
            className="w-full px-3 py-2 rounded text-sm"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
            }}
            autoFocus
          />
        </Field>

        <Field label={t('dashboard.sentiment.onboarding.field.ticker')}>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="VNET"
            className="w-full px-3 py-2 rounded text-sm font-mono"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
            }}
          />
        </Field>

        <Field label={t('dashboard.sentiment.onboarding.field.intent')}>
          <TagInput value={intents} onChange={setIntents} placeholder={t('account.brand.fields.intentPlaceholder')}
            suggestions={['做空报告', '业绩传闻', '高管变动', '海外业务', '竞品动态', '政策监管', '诉讼纠纷', '股价异动']} />
        </Field>

        <Field label={t('dashboard.sentiment.onboarding.field.keywords')}>
          <TagInput
            value={keywords}
            onChange={setKeywords}
            placeholder={t('dashboard.sentiment.settings.fields.tagPlaceholder')}
          />
        </Field>

        <Field label={t('dashboard.sentiment.onboarding.field.emails')}>
          <TagInput
            value={emails}
            onChange={setEmails}
            placeholder="ir@yourcompany.com"
            max={10}
          />
        </Field>

        {error && (
          <div className="rounded-md p-3 text-sm"
               style={{ background: 'rgba(239,68,68,0.1)', color: '#dc2626', border: '1px solid rgba(239,68,68,0.3)' }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={!canSubmit || submitting}
          className="btn-solid w-full rounded-md py-3 text-sm font-semibold disabled:opacity-50"
        >
          {submitting ? '...' : t('dashboard.sentiment.onboarding.submit')}
        </button>
      </form>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs font-semibold text-secondary uppercase tracking-wider block mb-1.5">
        {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
      </label>
      {children}
    </div>
  );
}
