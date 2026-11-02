import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { accountApi } from '../../services/accountApi';

interface StoredUser {
  id: number;
  email: string;
  name?: string | null;
  is_active: boolean;
}

type Ctx = { user: StoredUser | null };

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-tertiary)',
  border: '1px solid var(--border-color)',
  color: 'var(--text-primary)',
};

export function ProfileTab() {
  const { user } = useOutletContext<Ctx>();
  const { t } = useTranslation();

  const [oldPw, setOldPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    if (newPw.length < 6) {
      setMessage({ kind: 'error', text: t('account.profile.minLength', '新密码至少 6 位') });
      return;
    }
    if (newPw !== confirmPw) {
      setMessage({ kind: 'error', text: t('account.profile.mismatch', '两次输入的新密码不一致') });
      return;
    }
    const token = localStorage.getItem('token');
    if (!token) {
      setMessage({ kind: 'error', text: t('account.common.needLogin', '请先登录') });
      return;
    }
    setSubmitting(true);
    try {
      await accountApi.changePassword(token, oldPw, newPw);
      setMessage({ kind: 'success', text: t('account.profile.success', '密码修改成功') });
      setOldPw('');
      setNewPw('');
      setConfirmPw('');
    } catch (err) {
      setMessage({
        kind: 'error',
        text: err instanceof Error ? err.message : t('account.profile.failed', '修改失败'),
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="rounded-2xl p-6" style={cardStyle}>
        <h2 className="text-lg font-bold text-primary mb-4">
          {t('account.profile.accountInfo', '账号信息')}
        </h2>
        <dl className="text-sm">
          <div
            className="py-3 flex justify-between gap-4 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <dt className="text-secondary">{t('account.profile.email', '邮箱')}</dt>
            <dd className="text-primary font-medium break-all">{user?.email ?? '-'}</dd>
          </div>
          <div
            className="py-3 flex justify-between gap-4 border-b"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <dt className="text-secondary">{t('account.profile.status', '账号状态')}</dt>
            <dd className="text-primary font-medium">
              {user?.is_active
                ? t('account.profile.active', '正常')
                : t('account.profile.inactive', '已停用')}
            </dd>
          </div>
          <div className="py-3 flex justify-between gap-4">
            <dt className="text-secondary">{t('account.profile.userId', '用户 ID')}</dt>
            <dd className="text-primary font-medium">{user?.id ?? '-'}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-2xl p-6" style={cardStyle}>
        <h2 className="text-lg font-bold text-primary mb-4">
          {t('account.profile.changePassword', '修改密码')}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4 max-w-md">
          <div>
            <label className="block text-sm font-medium text-secondary mb-1">
              {t('account.profile.oldPassword', '当前密码')}
            </label>
            <input
              type="password"
              required
              value={oldPw}
              onChange={(e) => setOldPw(e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg focus:outline-none"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-secondary mb-1">
              {t('account.profile.newPassword', '新密码')}
            </label>
            <input
              type="password"
              required
              minLength={6}
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg focus:outline-none"
              style={inputStyle}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-secondary mb-1">
              {t('account.profile.confirmPassword', '确认新密码')}
            </label>
            <input
              type="password"
              required
              minLength={6}
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              className="w-full px-4 py-2.5 rounded-lg focus:outline-none"
              style={inputStyle}
            />
          </div>

          {message && (
            <div
              className="text-sm px-3 py-2 rounded-lg"
              style={
                message.kind === 'success'
                  ? {
                      background: 'rgba(0, 255, 157, 0.1)',
                      border: '1px solid rgba(0, 255, 157, 0.3)',
                      color: 'var(--success)',
                    }
                  : {
                      background: 'rgba(255, 0, 110, 0.1)',
                      border: '1px solid rgba(255, 0, 110, 0.3)',
                      color: '#ff006e',
                    }
              }
            >
              {message.text}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="btn-primary !py-2.5 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {submitting
              ? t('account.profile.submitting', '提交中...')
              : t('account.profile.submit', '更新密码')}
          </button>
        </form>
      </div>
    </div>
  );
}
