import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { authApi } from '../services/authApi';
import { useAuthModal } from '../contexts/AuthModalContext';
import { PageHead } from '../components/PageHead';

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const navigate = useNavigate();
  const { openAuthModal } = useAuthModal();
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  
  const resetToken = searchParams.get('token');
  const isResetMode = !!resetToken;

  const handleForgotPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccess('');

    try {
      await authApi.forgotPassword(email);
      setSuccess(t('forgotPassword.success.emailSent'));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('forgotPassword.error.sendFailed'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccess('');

    if (newPassword !== confirmPassword) {
      setError(t('register.error'));
      setIsLoading(false);
      return;
    }

    try {
      await authApi.resetPassword(resetToken!, newPassword);
      setSuccess(t('forgotPassword.success.resetSuccess'));
      // Redirect to home + open login modal after 2 seconds
      setTimeout(() => {
        navigate('/');
        openAuthModal('login');
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('forgotPassword.error.resetFailed'));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey="pageMeta.forgotPassword.title" descriptionKey="pageMeta.forgotPassword.description" />
      {/* 背景发光效果 */}
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 py-16 sm:py-24 hero-gradient relative z-10">
        <div className="w-full max-w-md mx-auto animate-fade-in">
          <div className="bg-card border border-border rounded-2xl p-8">
            <div className="text-center">
              <h2 className="mt-6 text-3xl font-bold text-primary">
                {isResetMode ? t('forgotPassword.reset.title') : t('forgotPassword.title')}
              </h2>
              <p className="mt-2 text-sm text-secondary">
                {isResetMode 
                  ? t('forgotPassword.reset.description') 
                  : t('forgotPassword.description')
                }
              </p>
            </div>

            {success && (
              <div className="mt-6 bg-green-900 border border-green-800 text-green-300 p-4 rounded-md text-sm">
                {success}
              </div>
            )}

            {error && (
              <div className="mt-6 bg-red-900 border border-red-800 text-red-300 p-4 rounded-md text-sm">
                {error}
              </div>
            )}

            {isResetMode ? (
              <form className="mt-8 space-y-6" onSubmit={handleResetPassword}>
                <div className="space-y-4">
                  <div>
                    <label htmlFor="new-password" className="block text-sm font-medium text-secondary mb-1">
                      {t('forgotPassword.reset.newPassword')}
                    </label>
                    <div className="relative">
                      <input
                        id="new-password"
                        name="new-password"
                        type={showNewPassword ? 'text' : 'password'}
                        required
                        value={newPassword}
                        onChange={(e) => setNewPassword(e.target.value)}
                        className="w-full px-4 py-3 pr-12 rounded-lg bg-card text-primary placeholder-muted focus:outline-none transition-colors duration-200"
                        placeholder={t('forgotPassword.reset.newPasswordPlaceholder')}
                      />
                      <button
                        type="button"
                        onClick={() => setShowNewPassword(!showNewPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-secondary hover:text-primary transition-colors"
                        tabIndex={-1}
                      >
                        {showNewPassword ? (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.59 6.59m7.532 7.532l3.29 3.29M3 3l18 18" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                  <div>
                    <label htmlFor="confirm-password" className="block text-sm font-medium text-secondary mb-1">
                      {t('forgotPassword.reset.confirmPassword')}
                    </label>
                    <div className="relative">
                      <input
                        id="confirm-password"
                        name="confirm-password"
                        type={showConfirmPassword ? 'text' : 'password'}
                        required
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        className="w-full px-4 py-3 pr-12 rounded-lg bg-card text-primary placeholder-muted focus:outline-none transition-colors duration-200"
                        placeholder={t('forgotPassword.reset.confirmPasswordPlaceholder')}
                      />
                      <button
                        type="button"
                        onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-secondary hover:text-primary transition-colors"
                        tabIndex={-1}
                      >
                        {showConfirmPassword ? (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L6.59 6.59m7.532 7.532l3.29 3.29M3 3l18 18" />
                          </svg>
                        ) : (
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full bg-accent-primary hover:bg-accent-primary/80 text-white font-semibold py-3 rounded-lg transition-colors duration-300 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading ? (
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    ) : null}
                    {isLoading ? t('forgotPassword.reset.loading') : t('forgotPassword.reset.button')}
                  </button>
                </div>
              </form>
            ) : (
              <form className="mt-8 space-y-6" onSubmit={handleForgotPassword}>
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-secondary mb-1">
                    {t('login.email')}
                  </label>
                  <input
                    id="email"
                    name="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-4 py-3 rounded-lg bg-card text-primary placeholder-muted focus:outline-none transition-colors duration-200"
                    placeholder={t('login.emailPlaceholder')}
                  />
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={isLoading}
                    className="w-full bg-accent-primary hover:bg-accent-primary/80 text-white font-semibold py-3 rounded-lg transition-colors duration-300 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLoading ? (
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                    ) : null}
                    {isLoading ? t('forgotPassword.loading') : t('forgotPassword.button')}
                  </button>
                </div>
              </form>
            )}

            <div className="mt-6 text-center">
              <Link
                to="/"
                onClick={(e) => { e.preventDefault(); navigate('/'); openAuthModal('login'); }}
                className="font-medium text-accent-primary hover:text-primary transition-colors duration-200 cursor-pointer"
              >
                {t('forgotPassword.backToLogin')}
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}