import { useTranslation } from 'react-i18next';
import { useLoadNs } from '../i18n/useLoadNs';
import { GeoKnowledgeTabs } from '../components/GeoKnowledgeTabs';
import { PageHead } from '../components/PageHead';

type Category = {
  id: string;
  items: string[];
};

const CATEGORIES: Category[] = [
  {
    id: 'crawlability',
    items: ['https', 'robots', 'sitemap', 'llms', 'aiCrawlerAccess'],
  },
  {
    id: 'structuredData',
    items: ['jsonld', 'metaTags', 'breadcrumbs', 'answerFormat'],
  },
  {
    id: 'authority',
    items: ['commonCrawl', 'wikipedia', 'knowledgeGraph', 'reviews', 'mentions'],
  },
  {
    id: 'visibility',
    items: ['citationRate', 'answerInclusion', 'shareOfVoice', 'sentimentFraming', 'contentGaps'],
  },
  {
    id: 'entity',
    items: ['entityClarity', 'categoryAssociation', 'platformCoverage', 'recognitionRate', 'stability'],
  },
];

function MetricCard({ ns }: { ns: string }) {
  const { t } = useTranslation();

  return (
    <article
      className="rounded-xl border p-6 sm:p-7"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border-color)',
      }}
    >
      <h3
        className="text-lg sm:text-xl font-bold mb-5 pb-4 border-b"
        style={{
          color: 'var(--text-primary)',
          borderColor: 'var(--border-color)',
        }}
      >
        {t(`${ns}.name`)}
      </h3>
      <div className="space-y-5">
        <div>
          <h4
            className="text-[11px] uppercase tracking-wider font-bold mb-2"
            style={{ color: 'var(--text-muted)' }}
          >
            {t('geoKnowledge.metrics.field.measures')}
          </h4>
          <p
            className="text-sm leading-relaxed"
            style={{ color: 'var(--text-primary)' }}
          >
            {t(`${ns}.measures`)}
          </p>
        </div>
        <div>
          <h4
            className="text-[11px] uppercase tracking-wider font-bold mb-2"
            style={{ color: 'var(--text-muted)' }}
          >
            {t('geoKnowledge.metrics.field.why')}
          </h4>
          <p
            className="text-sm leading-relaxed"
            style={{ color: 'var(--text-primary)' }}
          >
            {t(`${ns}.why`)}
          </p>
        </div>
        <div>
          <h4
            className="text-[11px] uppercase tracking-wider font-bold mb-2"
            style={{ color: 'var(--text-muted)' }}
          >
            {t('geoKnowledge.metrics.field.scoring')}
          </h4>
          <p
            className="text-sm leading-relaxed"
            style={{ color: 'var(--text-primary)' }}
          >
            {t(`${ns}.scoring`)}
          </p>
        </div>
      </div>
    </article>
  );
}

export function GeoKnowledgeMetrics() {
  useLoadNs('knowledge');
  const { t } = useTranslation();

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey="pageMeta.geoKnowledgeMetrics.title" descriptionKey="pageMeta.geoKnowledgeMetrics.description" />
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 py-16 sm:py-24 hero-gradient relative z-10">
        <div className="w-full max-w-5xl mx-auto animate-fade-in">
          <section className="hero mb-10">
            <div className="max-w-3xl mx-auto text-center">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 leading-tight">
                <span className="gradient-text">{t('geoKnowledge.metrics.title')}</span>
              </h1>
              <p
                className="text-lg sm:text-xl max-w-3xl mx-auto leading-relaxed"
                style={{ color: 'var(--text-secondary)' }}
              >
                {t('geoKnowledge.metrics.description')}
              </p>
            </div>
          </section>

          <GeoKnowledgeTabs />

          <section className="space-y-14">
            {CATEGORIES.map((cat) => (
              <div key={cat.id} className="animate-fade-in">
                <h2 className="text-2xl sm:text-3xl font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
                  {t(`geoKnowledge.metrics.categories.${cat.id}.title`)}
                </h2>
                <p
                  className="text-sm sm:text-base mb-6 max-w-3xl"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  {t(`geoKnowledge.metrics.categories.${cat.id}.description`)}
                </p>
                <div className="space-y-3">
                  {cat.items.map((item) => (
                    <MetricCard
                      key={item}
                      ns={`geoKnowledge.metrics.categories.${cat.id}.items.${item}`}
                    />
                  ))}
                </div>
              </div>
            ))}
          </section>
        </div>
      </main>
    </div>
  );
}
