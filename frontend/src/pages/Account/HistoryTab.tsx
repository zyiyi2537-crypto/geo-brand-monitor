import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { accountApi, type DetectionRecordSummary } from '../../services/accountApi';

const PAGE_SIZE = 10;

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

const borderBottomStyle: React.CSSProperties = {
  borderBottom: '1px solid var(--border-color)',
};

export function HistoryTab() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [items, setItems] = useState<DetectionRecordSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [viewingId, setViewingId] = useState<number | null>(null);

  const load = useCallback(async (targetPage: number) => {
    const token = localStorage.getItem('token');
    if (!token) return;
    setLoading(true);
    setError('');
    try {
      const data = await accountApi.listDetections(token, targetPage, PAGE_SIZE);
      setItems(data.items);
      setTotal(data.total);
      setPage(data.page);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(1);
  }, [load]);

  const handleView = async (id: number) => {
    const token = localStorage.getItem('token');
    if (!token) return;
    setViewingId(id);
    try {
      const detail = await accountApi.getDetection(token, id);
      navigate('/result', { state: { result: detail.result, fromHistory: true } });
    } catch (err) {
      alert(err instanceof Error ? err.message : t('common.errors.loadFailed'));
    } finally {
      setViewingId(null);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('account.history.deleteConfirm', '确定删除这条检测记录吗？'))) return;
    const token = localStorage.getItem('token');
    if (!token) return;
    try {
      await accountApi.deleteDetection(token, id);
      await load(page);
    } catch (err) {
      alert(err instanceof Error ? err.message : t('common.errors.deleteFailed'));
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div className="rounded-2xl overflow-hidden" style={cardStyle}>
        <div
          className="px-6 py-4 flex items-center justify-between"
          style={borderBottomStyle}
        >
          <h2 className="text-lg font-bold text-primary">
            {t('account.history.title', '检测记录')}
          </h2>
          <span className="text-sm text-secondary">
            {t('account.history.total', '共 {{n}} 条', { n: total })}
          </span>
        </div>

        {loading ? (
          <div className="p-10 text-center">
            <div
              className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 mx-auto"
              style={{ borderColor: 'var(--accent-primary)' }}
            />
          </div>
        ) : error ? (
          <div className="p-6 text-sm" style={{ color: '#ff006e' }}>
            {error}
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-secondary mb-4">
              {t('account.history.empty', '还没有检测记录')}
            </p>
            <button onClick={() => navigate('/')} className="btn-primary !py-2.5">
              {t('account.history.goCheck', '去检测一下')}
            </button>
          </div>
        ) : (
          <>
            {/* Mobile card layout */}
            <div className="sm:hidden divide-y" style={{ borderColor: 'var(--border-color)' }}>
              {items.map((row) => {
                const isDeleted = !!row.deleted_at;
                return (
                  <div
                    key={row.id}
                    className="px-4 py-4 space-y-2.5"
                    style={isDeleted ? { opacity: 0.5 } : undefined}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p
                        className="text-sm text-primary font-medium truncate flex-1 min-w-0"
                        title={row.url}
                        style={isDeleted ? { textDecoration: 'line-through' } : undefined}
                      >
                        {row.url}
                      </p>
                      <span
                        className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full shrink-0"
                        style={{
                          background: 'rgba(0, 240, 255, 0.1)',
                          border: '1px solid rgba(0, 240, 255, 0.3)',
                          color: 'var(--accent-primary)',
                        }}
                      >
                        {row.mode === 'advanced'
                          ? t('account.history.modeAdvanced', '高级')
                          : t('account.history.modeFree', '标准')}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-secondary">
                      <span style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                        {new Date(row.created_at).toLocaleString()}
                      </span>
                      {row.score != null && (
                        <span className="font-semibold text-primary" style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                          {row.score}{row.grade && <span className="text-secondary ml-0.5">({row.grade})</span>}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3 pt-1">
                      {isDeleted ? (
                        <span className="text-secondary text-xs">
                          {t('account.history.deleted', '已删除')}
                        </span>
                      ) : (
                        <>
                          <button
                            disabled={viewingId === row.id}
                            onClick={() => handleView(row.id)}
                            className="text-xs font-medium disabled:opacity-50"
                            style={{ color: 'var(--accent-primary)' }}
                          >
                            {viewingId === row.id
                              ? t('account.history.loading', '加载中...')
                              : t('account.history.view', '查看')}
                          </button>
                          <button
                            onClick={() => handleDelete(row.id)}
                            className="text-xs font-medium"
                            style={{ color: '#ff006e' }}
                          >
                            {t('account.history.delete', '删除')}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Desktop table layout */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead style={{ background: 'var(--bg-tertiary)' }}>
                  <tr className="text-secondary">
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.history.time', '时间')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.history.url', '网址')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.history.score', '得分')}
                    </th>
                    <th className="px-4 py-3 text-left font-medium">
                      {t('account.history.mode', '模式')}
                    </th>
                    <th className="px-4 py-3 text-right font-medium">
                      {t('account.history.actions', '操作')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, idx) => {
                    const isDeleted = !!row.deleted_at;
                    return (
                    <tr
                      key={row.id}
                      style={{
                        ...(idx < items.length - 1 ? borderBottomStyle : undefined),
                        ...(isDeleted ? { opacity: 0.5 } : undefined),
                      }}
                      className="transition-colors hover:bg-white/5"
                    >
                      <td className="px-4 py-3 text-secondary whitespace-nowrap" style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-primary max-w-xs truncate" style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                        <span title={row.url}>{row.url}</span>
                      </td>
                      <td className="px-4 py-3" style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                        {row.score != null ? (
                          <span className="inline-flex items-center gap-1 font-semibold text-primary">
                            {row.score}
                            {row.grade && (
                              <span className="text-xs text-secondary">({row.grade})</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-secondary">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3" style={isDeleted ? { textDecoration: 'line-through' } : undefined}>
                        <span
                          className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full"
                          style={{
                            background: 'rgba(0, 240, 255, 0.1)',
                            border: '1px solid rgba(0, 240, 255, 0.3)',
                            color: 'var(--accent-primary)',
                          }}
                        >
                          {row.mode === 'advanced'
                            ? t('account.history.modeAdvanced', '高级')
                            : t('account.history.modeFree', '标准')}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        {isDeleted ? (
                          <span className="text-secondary text-xs">
                            {t('account.history.deleted', '已删除')}
                          </span>
                        ) : (
                          <>
                            <button
                              disabled={viewingId === row.id}
                              onClick={() => handleView(row.id)}
                              className="font-medium mr-3 disabled:opacity-50"
                              style={{ color: 'var(--accent-primary)' }}
                            >
                              {viewingId === row.id
                                ? t('account.history.loading', '加载中...')
                                : t('account.history.view', '查看')}
                            </button>
                            <button
                              onClick={() => handleDelete(row.id)}
                              className="font-medium"
                              style={{ color: '#ff006e' }}
                            >
                              {t('account.history.delete', '删除')}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div
                className="px-6 py-3 flex items-center justify-between"
                style={{ borderTop: '1px solid var(--border-color)' }}
              >
                <span className="text-xs text-secondary">
                  {t('account.history.pageOf', '第 {{page}} / {{pages}} 页', {
                    page,
                    pages: totalPages,
                  })}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={page <= 1}
                    onClick={() => load(page - 1)}
                    className="btn-secondary !py-1.5 !px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {t('account.history.prev', '上一页')}
                  </button>
                  <button
                    disabled={page >= totalPages}
                    onClick={() => load(page + 1)}
                    className="btn-secondary !py-1.5 !px-3 text-sm disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {t('account.history.next', '下一页')}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
