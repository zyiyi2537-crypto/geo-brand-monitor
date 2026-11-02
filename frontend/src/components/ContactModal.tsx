import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useContactModal } from './ContactModalContext';

const HIDDEN_ROUTES = [
  '/login',
  '/register',
  '/forgot-password',
  '/checkout/pending',
  '/checkout/success',
  '/checkout/cancel',
];

const sanitizeInput = (input: string): string =>
  input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

export function ContactModal() {
  const { t } = useTranslation();
  const location = useLocation();
  const { isOpen, openContact, closeContact } = useContactModal();
  const [formData, setFormData] = useState({ name: '', email: '', website: '', message: '' });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const hidden = location.pathname === '/' || location.pathname === '/unified-monitor' || HIDDEN_ROUTES.some((p) => location.pathname.startsWith(p));
  if (hidden) return null;

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) { setError(t('contact.form.errors.name')); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) { setError(t('contact.form.errors.email')); return; }
    if (!formData.website.trim()) { setError(t('contact.form.errors.website')); return; }

    setIsLoading(true);
    setError('');
    setSuccess('');
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: sanitizeInput(formData.name),
          email: sanitizeInput(formData.email),
          website: sanitizeInput(formData.website),
          message: formData.message.trim() ? sanitizeInput(formData.message) : undefined,
        }),
      });
      if (!res.ok) throw new Error();
      setSuccess(t('contact.form.success'));
      setFormData({ name: '', email: '', website: '', message: '' });
    } catch {
      setError(t('contact.form.error'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    closeContact();
    setError('');
    setSuccess('');
  };

  const inputClass =
    'w-full px-4 py-2.5 rounded-lg text-sm bg-card text-primary placeholder-muted border border-border focus:outline-none focus:border-accent-primary transition-colors';

  // Collapsed bubble
  if (!isOpen) {
    return (
      <button
        onClick={openContact}
        aria-label={t('contact.fab.label') as string}
        className="fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-3 rounded-full font-semibold text-sm text-white shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all duration-200"
        style={{ background: 'var(--accent-primary)' }}
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        <span className="hidden sm:inline">{t('contact.fab.label')}</span>
      </button>
    );
  }

  // Expanded panel — desktop: bottom-right card; mobile: fullscreen (z-50 to cover Header)
  return (
    <div
      className="fixed inset-0 sm:inset-auto sm:bottom-6 sm:right-6 z-50 sm:w-[380px] sm:max-h-[80vh] flex flex-col shadow-2xl animate-fade-in sm:rounded-2xl overflow-hidden"
      style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-4 border-b"
        style={{ background: 'var(--accent-primary)', borderColor: 'var(--border-color)' }}
      >
        <div>
          <h2 className="text-base font-bold text-white">{t('contact.title')}</h2>
          <p className="text-xs text-white/80 mt-0.5">{t('contact.subtitle')}</p>
        </div>
        <button
          onClick={handleClose}
          aria-label="Close"
          className="flex-shrink-0 text-white/80 hover:text-white transition-colors ml-3"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-5">
        {success && (
          <div className="bg-green-900/50 border border-green-700 text-green-300 px-3 py-2 rounded-lg text-sm mb-4">
            {success}
          </div>
        )}
        {error && (
          <div className="bg-red-900/50 border border-red-700 text-red-300 px-3 py-2 rounded-lg text-sm mb-4">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">{t('contact.form.name')}</label>
            <input
              type="text" name="name" value={formData.name} onChange={handleChange}
              placeholder={t('contact.form.placeholders.name')} className={inputClass} disabled={isLoading}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">{t('contact.form.email')}</label>
            <input
              type="email" name="email" value={formData.email} onChange={handleChange}
              placeholder={t('contact.form.placeholders.email')} className={inputClass} disabled={isLoading}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">{t('contact.form.website')}</label>
            <input
              type="text" name="website" value={formData.website} onChange={handleChange}
              placeholder={t('contact.form.placeholders.website')} className={inputClass} disabled={isLoading}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-secondary mb-1">{t('contact.form.message')}</label>
            <textarea
              name="message" value={formData.message} onChange={handleChange}
              placeholder={t('contact.form.placeholders.message')} rows={3}
              className={`${inputClass} resize-none`} disabled={isLoading}
            />
          </div>
          <button
            type="submit" disabled={isLoading}
            className="w-full bg-accent-primary hover:bg-accent-primary/80 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? t('contact.form.sending') : t('contact.submit')}
          </button>
        </form>

        <div
          className="mt-4 pt-4 text-center text-xs text-secondary"
          style={{ borderTop: '1px solid var(--border-color)' }}
        >
          Email: <a href="mailto:support@zen7.com" className="text-accent-primary hover:underline">support@zen7.com</a>
        </div>
      </div>
    </div>
  );
}
