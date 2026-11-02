// 监测报告 — admin 视角的「效果查验与更新」反哺看板入口.
// 列出所有 approved 主题,点入跳到 /brand-growth/insights(用户端反哺数据看板).

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { adminReviewApi, type TopicReviewListItem } from '../../services/adminReviewApi';

const PAGE_SIZE = 10;

export function AdminInsights() {
  const { t } = useTranslation();
  const token = localStorage.getItem('token') || '';
  const [topics, setTopics] = useState<TopicReviewListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  useEffect(() => {
    adminReviewApi.listTopicReviews(token, 'approved')
      .then(setTopics)
      .catch(() => setTopics([]))
      .finally(() => setLoading(false));
  }, [token]);

  const totalPages = Math.max(1, Math.ceil(topics.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pagedTopics = topics.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <div className="space-y-4">
      <PageHead titleKey="workbench.adminInsights.title" titleFallback="监测报告" />
      <header>
        <h1 className="text-xl font-semibold text-primary">
          {t('workbench.adminInsights.heading')}
        </h1>
        <p className="text-xs text-secondary mt-0.5">
          {t('workbench.adminInsights.subtitle')}
        </p>
      </header>

      {loading ? (
        <div className="text-xs text-muted text-center py-10">{t('common.loading')}</div>
      ) : topics.length === 0 ? (
        <div className="text-xs text-muted text-center py-10">{t('workbench.adminInsights.empty')}</div>
      ) : (
        <>
          <p className="text-xs text-muted">{t('workbench.adminInsights.pickTopic')}</p>
          <div className="rounded-lg overflow-hidden"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <table className="w-full text-xs">
              <tbody>
                {pagedTopics.map(tp => (
                  <tr key={tp.topic_id} className="border-t"
                      style={{ borderColor: 'var(--border-color)' }}>
                    <td className="px-3 py-2 text-primary">
                      {tp.profile_name || tp.topic_name}
                      <span className="ml-2 text-[10px] text-muted">#{tp.topic_id}</span>
                    </td>
                    <td className="px-3 py-2 text-secondary">{tp.user_email}</td>
                    <td className="px-3 py-2 text-right">
                      <Link to={`/brand-growth/insights?topicId=${tp.topic_id}`}
                            className="text-accent hover:underline">
                        {t('workbench.adminInsights.view')}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {topics.length > PAGE_SIZE && (
            <div className="flex items-center justify-between text-xs text-secondary pt-1">
              <span className="tabular-nums text-muted">
                {t('workbench.adminInsights.pageRange', {
                  from: (safePage - 1) * PAGE_SIZE + 1,
                  to: Math.min(safePage * PAGE_SIZE, topics.length),
                  total: topics.length,
                })}
              </span>
              <div className="flex items-center gap-2">
                <button type="button" disabled={safePage <= 1}
                        onClick={() => setPage(Math.max(1, safePage - 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminInsights.prev')}
                </button>
                <span className="tabular-nums">{safePage} / {totalPages}</span>
                <button type="button" disabled={safePage >= totalPages}
                        onClick={() => setPage(Math.min(totalPages, safePage + 1))}
                        className="px-2 py-1 rounded-md disabled:opacity-40"
                        style={{ background: 'var(--bg-tertiary)' }}>
                  {t('workbench.adminInsights.next')}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
