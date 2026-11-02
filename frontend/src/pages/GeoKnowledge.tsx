import { useTranslation } from 'react-i18next';
import { useLoadNs } from '../i18n/useLoadNs';
import { GeoKnowledgeTabs } from '../components/GeoKnowledgeTabs';
import { PageHead } from '../components/PageHead';

export function GeoKnowledge() {
  useLoadNs('knowledge');
  const { t } = useTranslation();

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey="pageMeta.geoKnowledge.title" descriptionKey="pageMeta.geoKnowledge.description" />
      {/* 背景发光效果 */}
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      {/* 主内容 */}
      <main className="flex-1 px-4 py-16 sm:py-24 hero-gradient relative z-10">
        <div className="w-full max-w-6xl mx-auto animate-fade-in">
          {/* Hero Section */}
          <section className="hero mb-10">
            <div className="max-w-3xl mx-auto text-center">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 leading-tight animate-slide-up">
                <span className="gradient-text">{t('geoKnowledge.title')}</span>
              </h1>
              <p className="text-lg sm:text-xl text-secondary max-w-3xl mx-auto leading-relaxed animate-slide-up" style={{ animationDelay: '0.1s' }}>
                {t('geoKnowledge.description')}
              </p>
            </div>
          </section>

          <GeoKnowledgeTabs />

          {/* Content Section */}
          <section className="space-y-20">
            {/* About GEO */}
            <div className="animate-fade-in" style={{ animationDelay: '0.2s' }}>
              <h2 className="text-3xl font-bold mb-8 text-center">
                <span className="gradient-text">{t('geoKnowledge.sections.about')}</span>
              </h2>
              <div className="bg-card border border-border rounded-2xl p-8">
                <h3 className="text-xl font-bold mb-4">{t('geoKnowledge.sections.whatIsGeo')}</h3>
                <p className="text-secondary mb-6 leading-relaxed">
                  {t('geoKnowledge.sections.whatIsGeoBody')}
                </p>
                <h3 className="text-xl font-bold mb-4">{t('geoKnowledge.sections.whyGeoImportant')}</h3>
                <ul className="space-y-3 text-secondary">
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-accent-primary shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                    <span>{t('geoKnowledge.sections.whyGeoPoints.0')}</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-accent-primary shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                    <span>{t('geoKnowledge.sections.whyGeoPoints.1')}</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-accent-primary shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                    <span>{t('geoKnowledge.sections.whyGeoPoints.2')}</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-accent-primary shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                    <span>{t('geoKnowledge.sections.whyGeoPoints.3')}</span>
                  </li>
                </ul>
              </div>
            </div>

            {/* GEO Strategies */}
            <div className="animate-fade-in" style={{ animationDelay: '0.3s' }}>
              <h2 className="text-3xl font-bold mb-8 text-center">
                <span className="gradient-text">{t('geoKnowledge.sections.strategies')}</span>
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div className="bg-card border border-border rounded-2xl p-8">
                  <h3 className="text-xl font-bold mb-4">{t('geoKnowledge.sections.contentLocalization')}</h3>
                  <p className="text-secondary mb-4 leading-relaxed">
                    {t('geoKnowledge.sections.contentLocalizationDesc')}
                  </p>
                  <ul className="space-y-2 text-secondary">
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.contentLocalizationPoints.0')}</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.contentLocalizationPoints.1')}</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.contentLocalizationPoints.2')}</span>
                    </li>
                  </ul>
                </div>
                <div className="bg-card border border-border rounded-2xl p-8">
                  <h3 className="text-xl font-bold mb-4">{t('geoKnowledge.sections.technicalOptimization')}</h3>
                  <p className="text-secondary mb-4 leading-relaxed">
                    {t('geoKnowledge.sections.technicalOptimizationDesc')}
                  </p>
                  <ul className="space-y-2 text-secondary">
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.technicalOptimizationPoints.0')}</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.technicalOptimizationPoints.1')}</span>
                    </li>
                    <li className="flex items-center gap-2">
                      <svg className="w-4 h-4 text-accent-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span>{t('geoKnowledge.sections.technicalOptimizationPoints.2')}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            {/* GEO Key Data */}
            <div className="animate-fade-in" style={{ animationDelay: '0.4s' }}>
              <h2 className="text-3xl font-bold mb-8 text-center">
                <span className="gradient-text">{t('geoKnowledge.sections.keyData')}</span>
              </h2>
              <div className="bg-card border border-border rounded-2xl p-8">
                <h3 className="text-xl font-bold mb-4">{t('geoKnowledge.sections.importantMetrics')}</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <div className="border border-border rounded-xl p-6">
                    <h4 className="font-semibold mb-2">{t('geoKnowledge.sections.regionalTraffic')}</h4>
                    <p className="text-secondary text-sm">{t('geoKnowledge.sections.regionalTrafficDesc')}</p>
                  </div>
                  <div className="border border-border rounded-xl p-6">
                    <h4 className="font-semibold mb-2">{t('geoKnowledge.sections.languagePreference')}</h4>
                    <p className="text-secondary text-sm">{t('geoKnowledge.sections.languagePreferenceDesc')}</p>
                  </div>
                  <div className="border border-border rounded-xl p-6">
                    <h4 className="font-semibold mb-2">{t('geoKnowledge.sections.searchTrends')}</h4>
                    <p className="text-secondary text-sm">{t('geoKnowledge.sections.searchTrendsDesc')}</p>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
