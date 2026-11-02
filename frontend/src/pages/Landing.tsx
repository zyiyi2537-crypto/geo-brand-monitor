import { useTranslation } from 'react-i18next';
import { useNavigate, useLocation } from 'react-router-dom';
import { PageHead } from '../components/PageHead';

export function Landing() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const pathToKey: Record<string, string> = {
    '/pricing': 'pricing',
    '/data': 'data',
    '/process': 'process',
  };
  const metaKey = pathToKey[location.pathname] ?? 'process';

  const scrollToSection = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const aboutCards = [
    {
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
        </svg>
      ),
      title: t('about.definition'),
      text: t('about.definitionText'),
      bgColor: 'bg-indigo-500/10',
      textColor: 'text-indigo-600',
    },
    {
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
        </svg>
      ),
      title: t('about.combination'),
      text: t('about.combinationText'),
      bgColor: 'bg-cyan-500/10',
      textColor: 'text-cyan-600',
    },
    {
      icon: (
        <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
        </svg>
      ),
      title: t('about.difference'),
      text: t('about.differenceText'),
      bgColor: 'bg-purple-500/10',
      textColor: 'text-purple-600',
    },
  ];

  const processSteps = [
    {
      step: '01',
      title: t('process.step1.title'),
      description: t('process.step1.description'),
    },
    {
      step: '02',
      title: t('process.step2.title'),
      description: t('process.step2.description'),
    },
    {
      step: '03',
      title: t('process.step3.title'),
      description: t('process.step3.description'),
    },
    {
      step: '04',
      title: t('process.step4.title'),
      description: t('process.step4.description'),
    },
  ];

  const pricingTiers = [
    {
      name: t('pricing.tier1.name'),
      price: t('pricing.tier1.price'),
      priceEnd: t('pricing.tier1.priceEnd'),
      period: t('pricing.tier1.period'),
      description: t('pricing.tier1.description'),
      features: t('pricing.tier1.features', { returnObjects: true }) as string[],
      notIncluded: t('pricing.tier1.notIncluded', { returnObjects: true }) as string[],
    },
    {
      name: t('pricing.tier2.name'),
      price: t('pricing.tier2.price'),
      priceEnd: t('pricing.tier2.priceEnd'),
      period: t('pricing.tier2.period'),
      description: t('pricing.tier2.description'),
      features: t('pricing.tier2.features', { returnObjects: true }) as string[],
      notIncluded: t('pricing.tier2.notIncluded', { returnObjects: true }) as string[],
      popular: true,
    },
    {
      name: t('pricing.tier3.name'),
      price: t('pricing.tier3.price'),
      priceEnd: t('pricing.tier3.priceEnd'),
      period: t('pricing.tier3.period'),
      description: t('pricing.tier3.description'),
      features: t('pricing.tier3.features', { returnObjects: true }) as string[],
      notIncluded: [],
    },
  ];

  return (
    <div className="min-h-screen">
      <PageHead titleKey={`pageMeta.${metaKey}.title`} descriptionKey={`pageMeta.${metaKey}.description`} />

      {/* Hero Section */}
      <section className="relative min-h-screen flex items-center justify-center hero-gradient overflow-hidden pt-16">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,rgba(59,130,246,0.3),transparent_50%)]"></div>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,rgba(29,78,210,0.2),transparent_50%)]"></div>
        <div className="relative z-10 max-w-4xl mx-auto px-6 text-center">
          <p className="inline-block mb-6 px-4 py-1.5 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 text-white/90 text-sm font-medium tracking-wide">
            {t('hero.subtitle')}
          </p>
          <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white leading-tight mb-6">
            {t('hero.title')}
          </h1>
          <p className="text-lg md:text-xl text-white/80 max-w-2xl mx-auto mb-10 leading-relaxed">
            {t('hero.description')}
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={() => scrollToSection('about')}
              className="inline-flex items-center justify-center px-8 py-3.5 rounded-lg border-2 border-white/30 text-white font-semibold hover:bg-white/10 transition-all duration-300"
            >
              {t('hero.cta')}
            </button>
            <button
              onClick={() => scrollToSection('contact')}
              className="inline-flex items-center justify-center px-8 py-3.5 rounded-lg bg-white text-blue-700 font-semibold shadow-lg shadow-white/25 hover:shadow-xl hover:shadow-white/30 hover:-translate-y-0.5 transition-all duration-300"
            >
              {t('hero.ctaSecondary')}
            </button>
          </div>
        </div>
        <div className="absolute bottom-8 left-1/2 -translate-x-1/2 animate-bounce">
          <svg className="w-6 h-6 text-white/60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
          </svg>
        </div>
      </section>

      {/* About Section */}
      <section id="about" className="py-20 md:py-28 bg-gray-50">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <span className="inline-block px-4 py-1 rounded-full bg-blue-500/10 text-blue-600 text-sm font-semibold tracking-wide mb-4">
              {t('about.sectionTag')}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
              {t('about.title')}
            </h2>
            <p className="text-gray-600 max-w-3xl mx-auto text-lg leading-relaxed">
              {t('about.description')}
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {aboutCards.map((card, index) => (
              <article key={index} className="group card p-8 hover:shadow-xl hover:-translate-y-1 transition-all duration-300 card-hover">
                <div className={`inline-flex items-center justify-center w-14 h-14 rounded-xl bg-blue-500/20 text-blue-400 mb-6`}>
                  {card.icon}
                </div>
                <h3 className="text-xl font-bold text-gray-900 mb-4">
                  {card.title}
                </h3>
                <p className="text-gray-600 leading-relaxed">
                  {card.text}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Process Section */}
      <section id="process" className="py-20 md:py-28 bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <span className="inline-block px-4 py-1 rounded-full bg-blue-500/10 text-blue-600 text-sm font-semibold tracking-wide mb-4">
              {t('process.sectionTag')}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
              {t('process.title')}
            </h2>
            <p className="text-gray-600 max-w-2xl mx-auto text-lg">
              {t('process.subtitle')}
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            {processSteps.map((step, index) => (
              <div key={index} className="relative">
                <div className="text-6xl font-bold text-blue-100 mb-4">{step.step}</div>
                <h3 className="text-xl font-bold text-gray-900 mb-3">{step.title}</h3>
                <p className="text-gray-600 leading-relaxed">{step.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-20 md:py-28 bg-gray-50">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <span className="inline-block px-4 py-1 rounded-full bg-blue-500/10 text-blue-600 text-sm font-semibold tracking-wide mb-4">
              {t('pricing.sectionTag')}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
              {t('pricing.title')}
            </h2>
            <p className="text-gray-600 max-w-2xl mx-auto text-lg">
              {t('pricing.subtitle')}
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {pricingTiers.map((tier, index) => (
              <div
                key={index}
                className={`relative card ${tier.popular ? 'border border-blue-500 shadow-xl' : ''} p-8 hover:shadow-xl transition-all duration-300 card-hover`}
              >
                {tier.popular && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 bg-blue-600 text-white text-sm font-semibold rounded-full">
                    Popular
                  </div>
                )}
                <h3 className="text-xl font-bold text-gray-900 mb-2">{tier.name}</h3>
                <div className="mb-4">
                  <span className="text-4xl font-bold text-gray-900">{tier.price}</span>
                  <span className="text-gray-500">{tier.priceEnd}{tier.period}</span>
                </div>
                <p className="text-gray-600 mb-6">{tier.description}</p>
                <ul className="space-y-3 mb-8">
                  {tier.features.map((feature, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <svg className="w-5 h-5 text-green-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path>
                      </svg>
                      <span className="text-gray-700">{feature}</span>
                    </li>
                  ))}
                  {tier.notIncluded.map((feature, i) => (
                    <li key={i} className="flex items-start gap-3 opacity-50">
                      <svg className="w-5 h-5 text-gray-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path>
                      </svg>
                      <span className="text-gray-500 line-through">{feature}</span>
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => scrollToSection('contact')}
                  className={`w-full py-3 rounded-lg font-semibold transition-all duration-300 ${
                    tier.popular
                      ? 'bg-blue-600 text-white hover:bg-blue-700'
                      : 'bg-gray-100 text-gray-900 hover:bg-gray-200'
                  }`}
                >
                  {t('pricing.cta')}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Data Section */}
      <section id="data" className="py-20 md:py-28 bg-white">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <span className="inline-block px-4 py-1 rounded-full bg-blue-500/10 text-blue-600 text-sm font-semibold tracking-wide mb-4">
              {t('data.sectionTag')}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
              {t('data.title')}
            </h2>
            <p className="text-gray-600 max-w-2xl mx-auto text-lg">
              {t('data.subtitle')}
            </p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-16">
            <div className="text-center">
              <div className="text-4xl md:text-5xl font-bold text-blue-600 mb-2">{t('data.stat1.value')}</div>
              <div className="text-gray-600">{t('data.stat1.label')}</div>
            </div>
            <div className="text-center">
              <div className="text-4xl md:text-5xl font-bold text-blue-600 mb-2">{t('data.stat2.value')}</div>
              <div className="text-gray-600">{t('data.stat2.label')}</div>
            </div>
            <div className="text-center">
              <div className="text-4xl md:text-5xl font-bold text-blue-600 mb-2">{t('data.stat3.value')}</div>
              <div className="text-gray-600">{t('data.stat3.label')}</div>
            </div>
            <div className="text-center">
              <div className="text-4xl md:text-5xl font-bold text-blue-600 mb-2">{t('data.stat4.value')}</div>
              <div className="text-gray-600">{t('data.stat4.label')}</div>
            </div>
          </div>
          <div className="bg-gray-50 rounded-2xl p-8">
            <h3 className="text-xl font-bold text-gray-900 mb-6 text-center">{t('data.platforms.title')}</h3>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
              <div className="card p-4 text-center">
                <div className="font-semibold text-gray-900">ChatGPT</div>
              </div>
              <div className="card p-4 text-center">
                <div className="font-semibold text-gray-900">Gemini</div>
              </div>
              <div className="card p-4 text-center">
                <div className="font-semibold text-gray-900">Perplexity</div>
              </div>
              <div className="card p-4 text-center">
                <div className="font-semibold text-gray-900">Claude</div>
              </div>
              <div className="card p-4 text-center">
                <div className="font-semibold text-gray-900">Copilot</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Contact Section */}
      <section id="contact" className="py-20 md:py-28 bg-gray-50">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <span className="inline-block px-4 py-1 rounded-full bg-blue-500/10 text-blue-600 text-sm font-semibold tracking-wide mb-4">
              {t('contact.sectionTag')}
            </span>
            <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-6">
              {t('contact.title')}
            </h2>
            <p className="text-gray-600 max-w-2xl mx-auto text-lg">
              {t('contact.subtitle')}
            </p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-10">
            <div className="lg:col-span-3">
              <form className="card p-8 shadow-sm">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-6">
                  <div>
                    <label htmlFor="name" className="block text-sm font-semibold text-gray-900 mb-2">
                      {t('contact.name')}
                    </label>
                    <input
                      type="text"
                      id="name"
                      name="name"
                      required
                      className="input-field w-full"
                    />
                  </div>
                  <div>
                    <label htmlFor="email" className="block text-sm font-semibold text-gray-900 mb-2">
                      {t('contact.email')}
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      required
                      className="input-field w-full"
                    />
                  </div>
                </div>
                <div className="mb-6">
                  <label htmlFor="company" className="block text-sm font-semibold text-gray-900 mb-2">
                    {t('contact.company')}
                  </label>
                  <input
                    type="text"
                    id="company"
                    name="company"
                    className="input-field w-full"
                  />
                </div>
                <div className="mb-6">
                  <label htmlFor="message" className="block text-sm font-semibold text-gray-900 mb-2">
                    {t('contact.message')}
                  </label>
                  <textarea
                    id="message"
                    name="message"
                    rows={5}
                    required
                    className="input-field w-full resize-none"
                  ></textarea>
                </div>
                <button
                  type="submit"
                  className="btn-primary w-full py-3.5"
                >
                  {t('contact.submit')}
                </button>
              </form>
            </div>
            <div className="lg:col-span-2">
              <div className="card p-8 h-full flex flex-col justify-center">
                <h3 className="text-xl font-bold text-gray-900 mb-8">
                  {t('contact.sectionTag')}
                </h3>
                <div className="space-y-6">
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center shrink-0">
                      <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path>
                      </svg>
                    </div>
                    <div>
                      <p className="text-sm text-gray-500 mb-1">Email</p>
                      <a href={`mailto:${t('contact.info.email')}`} className="text-gray-900 font-semibold hover:text-blue-600 transition-colors duration-200">
                        {t('contact.info.email')}
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* GEO Tool CTA Section */}
      <section className="py-16 bg-blue-600">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="text-2xl md:text-3xl font-bold text-white mb-4">
            {t('geoTool.title', 'Want to check your website GEO readiness?')}
          </h2>
          <p className="text-white/80 mb-8">
            {t('geoTool.description', 'Use our free GEO Readiness Checker to analyze your website.')}
          </p>
          <button
            onClick={() => navigate('/checker')}
            className="inline-flex items-center justify-center px-8 py-3.5 rounded-lg bg-white text-blue-600 font-semibold shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300"
          >
            {t('geoTool.cta', 'Check Your Website')}
          </button>
        </div>
      </section>

    </div>
  );
}
