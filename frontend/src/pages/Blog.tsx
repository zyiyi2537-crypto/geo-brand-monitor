import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { PageHead } from '../components/PageHead';
import { blogPosts } from '../data/blogPosts';

export function Blog() {
  const { t, i18n } = useTranslation();
  const lang = i18n.language === 'en' ? 'en' : 'zh';

  // 最新文章在前
  const posts = [...blogPosts].sort((a, b) => b.date.localeCompare(a.date));

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(lang === 'en' ? 'en-US' : 'zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

  return (
    <div className="min-h-screen grid-background">
      <PageHead titleKey="pageMeta.blog.title" descriptionKey="pageMeta.blog.description" />
      <div className="bg-glow bg-glow-1"></div>
      <div className="bg-glow bg-glow-2"></div>
      <div className="bg-glow bg-glow-3"></div>

      <main className="flex-1 px-4 py-16 sm:py-24 hero-gradient relative z-10">
        <div className="w-full max-w-6xl mx-auto animate-fade-in">
          {/* Hero */}
          <section className="hero mb-16">
            <div className="max-w-3xl mx-auto text-center">
              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold mb-6 leading-tight animate-slide-up">
                <span className="gradient-text">{t('blog.title')}</span>
              </h1>
              <p
                className="text-lg sm:text-xl text-secondary max-w-3xl mx-auto leading-relaxed animate-slide-up"
                style={{ animationDelay: '0.1s' }}
              >
                {t('blog.subtitle')}
              </p>
            </div>
          </section>

          {/* Article grid */}
          <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {posts.map((post, idx) => {
              const c = post[lang];
              return (
                <Link
                  key={post.slug}
                  to={`/blog/${post.slug}`}
                  className="group bg-card border border-border rounded-2xl overflow-hidden flex flex-col hover:shadow-lg hover:shadow-accent-primary/10 transition-all duration-300 hover:-translate-y-1 animate-fade-in"
                  style={{ animationDelay: `${0.1 + idx * 0.05}s` }}
                >
                  {post.cover && (
                    <div className="aspect-[16/9] overflow-hidden">
                      <img
                        src={post.cover}
                        alt=""
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                        loading="lazy"
                      />
                    </div>
                  )}
                  <div className="p-6 flex flex-col flex-1">
                    <div className="flex items-center gap-2 text-xs text-muted mb-3">
                      <span>{formatDate(post.date)}</span>
                      <span>·</span>
                      <span>{t('blog.readingTime', { minutes: post.readingMinutes })}</span>
                    </div>
                    <h2 className="text-xl font-bold mb-3 text-primary group-hover:text-accent-primary transition-colors duration-200">
                      {c.title}
                    </h2>
                    <p className="text-secondary text-sm leading-relaxed line-clamp-3 flex-1">
                      {c.excerpt}
                    </p>
                    <span className="inline-flex items-center gap-1 mt-4 text-sm font-semibold text-accent-primary">
                      {t('blog.readMore')}
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </span>
                  </div>
                </Link>
              );
            })}
          </section>
        </div>
      </main>
    </div>
  );
}
