// AI 爬虫分析(admin 专属)— 读 vigilath 正式环境自己的 nginx 访问日志,
// 展示哪些 AI 爬虫来过、读了哪些页、频率与状态码.不接受用户上传日志.
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { adminCrawlApi, type CrawlAnalysis, type CrawlBot } from '../../services/adminCrawlApi';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function StatusCodes({ codes }: { codes: Record<string, number> }) {
  return (
    <span className="space-x-1">
      {Object.entries(codes).map(([code, n]) => {
        const ok = code.startsWith('2');
        const redirect = code.startsWith('3');
        const color = ok
          ? 'text-green-600'
          : redirect
            ? 'text-amber-600'
            : 'text-red-600';
        return (
          <span key={code} className={`text-xs ${color}`}>
            {code}×{n}
          </span>
        );
      })}
    </span>
  );
}

function BotRow({ bot }: { bot: CrawlBot }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr className="border-b border-[var(--border-color)] hover:bg-surface-hover">
        <td className="py-2 pr-3">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="font-medium text-primary hover:underline text-left"
          >
            {bot.name}
          </button>
          <div className="text-xs text-secondary">{bot.powers}</div>
        </td>
        <td className="py-2 pr-3">
          <span
            className={`text-xs px-1.5 py-0.5 rounded ${
              bot.importance === 'critical'
                ? 'bg-indigo-500/10 text-indigo-600'
                : 'bg-gray-500/10 text-secondary'
            }`}
          >
            {bot.importance === 'critical'
              ? t('workbench.adminCrawl.core')
              : t('workbench.adminCrawl.optional')}
          </span>
        </td>
        <td className="py-2 pr-3 text-right tabular-nums">{bot.requests.toLocaleString()}</td>
        <td className="py-2 pr-3 text-right tabular-nums">{bot.unique_pages}</td>
        <td className="py-2 pr-3 text-right tabular-nums">{bot.ips}</td>
        <td className="py-2 pr-3"><StatusCodes codes={bot.status_codes} /></td>
        <td className="py-2 pr-3 text-xs text-secondary whitespace-nowrap">{fmtTime(bot.last_seen)}</td>
      </tr>
      {open && (
        <tr className="border-b border-[var(--border-color)] bg-surface-hover/40">
          <td colSpan={7} className="py-2 px-3">
            <div className="text-xs text-secondary mb-1">
              {t('workbench.adminCrawl.topPages')} · {t('workbench.adminCrawl.firstSeen')}: {fmtTime(bot.first_seen)}
            </div>
            <ul className="space-y-0.5">
              {bot.top_pages.map((p) => (
                <li key={p.path} className="text-xs text-primary font-mono">
                  <span className="text-secondary tabular-nums">{p.count}×</span> {p.path}
                </li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  );
}

export function AdminCrawl() {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [data, setData] = useState<CrawlAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    adminCrawlApi
      .getAnalysis(token)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      <PageHead titleKey="workbench.adminCrawl.title" titleFallback="AI 爬虫分析" />
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-primary">{t('workbench.adminCrawl.heading')}</h1>
          <p className="text-xs text-secondary mt-0.5">{t('workbench.adminCrawl.subtitle')}</p>
          {data?.generated_at && (
            <p className="text-xs text-secondary mt-0.5">
              {t('workbench.adminCrawl.generatedAt')}: {fmtTime(data.generated_at)}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => load()}
          disabled={loading}
          className="text-sm px-3 py-1.5 rounded border border-[var(--border-color)] text-primary hover:bg-surface-hover disabled:opacity-50"
        >
          {loading ? t('workbench.adminCrawl.loading') : t('workbench.adminCrawl.refresh')}
        </button>
      </header>

      {error && (
        <div className="text-sm text-red-600 border border-red-500/30 rounded p-3">{error}</div>
      )}

      {loading && !data && (
        <div className="text-sm text-secondary">{t('workbench.adminCrawl.loading')}</div>
      )}

      {data && (
        <>
          {/* 概览卡片 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="card p-3">
              <div className="text-xs text-secondary">{t('workbench.adminCrawl.period')}</div>
              <div className="text-sm text-primary mt-1">
                {data.period.first ? fmtTime(data.period.first) : '—'}
              </div>
              <div className="text-xs text-secondary">→ {data.period.last ? fmtTime(data.period.last) : '—'}</div>
            </div>
            <div className="card p-3">
              <div className="text-xs text-secondary">{t('workbench.adminCrawl.totalLines')}</div>
              <div className="text-xl font-semibold text-primary mt-1 tabular-nums">
                {data.total_lines.toLocaleString()}
              </div>
            </div>
            <div className="card p-3">
              <div className="text-xs text-secondary">{t('workbench.adminCrawl.botRequests')}</div>
              <div className="text-xl font-semibold text-primary mt-1 tabular-nums">
                {data.total_bot_requests.toLocaleString()}
              </div>
            </div>
            <div className="card p-3">
              <div className="text-xs text-secondary">{t('workbench.adminCrawl.files')}</div>
              <div className="text-xl font-semibold text-primary mt-1 tabular-nums">
                {data.files.length}
              </div>
              <div className="text-xs text-secondary">{data.total_size_mb} MB</div>
            </div>
          </div>

          {/* 爬虫明细表 */}
          {data.bots.length > 0 ? (
            <div className="card p-3 overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-xs text-secondary border-b border-[var(--border-color)]">
                    <th className="py-2 pr-3 font-medium">{t('workbench.adminCrawl.colBot')}</th>
                    <th className="py-2 pr-3 font-medium">{t('workbench.adminCrawl.colType')}</th>
                    <th className="py-2 pr-3 font-medium text-right">{t('workbench.adminCrawl.colRequests')}</th>
                    <th className="py-2 pr-3 font-medium text-right">{t('workbench.adminCrawl.colPages')}</th>
                    <th className="py-2 pr-3 font-medium text-right">{t('workbench.adminCrawl.colIps')}</th>
                    <th className="py-2 pr-3 font-medium">{t('workbench.adminCrawl.colStatus')}</th>
                    <th className="py-2 pr-3 font-medium">{t('workbench.adminCrawl.colLastSeen')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bots.map((b) => (
                    <BotRow key={b.name} bot={b} />
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-secondary mt-2">{t('workbench.adminCrawl.rowHint')}</p>
            </div>
          ) : (
            <div className="text-sm text-secondary">{t('workbench.adminCrawl.noBots')}</div>
          )}

          {/* 未出现的爬虫 */}
          {(data.missing_critical.length > 0 || data.missing_optional.length > 0) && (
            <div className="card p-3 space-y-2">
              <div className="text-sm font-medium text-primary">{t('workbench.adminCrawl.notSeen')}</div>
              {data.missing_critical.length > 0 && (
                <div className="text-xs text-amber-600">
                  {t('workbench.adminCrawl.notSeenCore')}: {data.missing_critical.map((m) => m.name).join('、')}
                </div>
              )}
              {data.missing_optional.length > 0 && (
                <div className="text-xs text-secondary">
                  {t('workbench.adminCrawl.notSeenOptional')}: {data.missing_optional.map((m) => m.name).join('、')}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
