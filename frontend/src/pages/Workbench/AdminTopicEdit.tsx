// 项目内「画像」页 — stepper step 1 落地,套壳 TopicEditor 让 admin 在项目上下文里
// 编辑资料/种子/监测问题,不再跳到客户列表页的弹层模式.
// 路由:/workbench/topics/:topicId/edit

import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageHead } from '../../components/PageHead';
import { TopicEditor } from '../Dashboard/AiTelemetry';
import { aiTelemetryApi, type Topic, type TopicPayload } from '../../services/aiTelemetryApi';
import { adminReviewApi } from '../../services/adminReviewApi';

export function AdminTopicEdit() {
  const { t } = useTranslation();
  const { topicId } = useParams();
  const navigate = useNavigate();
  const tid = Number(topicId);
  const token = localStorage.getItem('token') || '';
  // 项目进度看板把 6 段 chip 都指向 /edit?step=N,这里读出来透传给 TopicEditor.
  const [searchParams] = useSearchParams();
  const stepParam = Number(searchParams.get('step'));
  const initialStep =
    stepParam >= 1 && stepParam <= 7 ? (stepParam as 1 | 2 | 3 | 4 | 5 | 6 | 7) : undefined;

  const [topic, setTopic] = useState<Topic | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!tid) return;
    let cancelled = false;
    adminReviewApi.getTopicReview(tid, token)
      .then((d) => {
        if (cancelled) return;
        setTopic(d);
        setUserId(d.user_id);
      })
      .catch((e) => { if (!cancelled) setErr(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tid, token]);

  const handleSave = async (payload: TopicPayload): Promise<Topic> => {
    return aiTelemetryApi.updateTopic(tid, payload, token);
  };

  return (
    <div className="space-y-4">
      <PageHead titleKey="workbench.topicStepper.profile" titleFallback="画像" />

      {err && (
        <div className="rounded-md p-3 text-sm"
             style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                      border: '1px solid rgba(239,68,68,0.3)' }}>
          {err}
        </div>
      )}

      {loading && !topic && (
        <div className="py-12 text-center text-sm text-muted">{t('common.loading')}</div>
      )}

      {topic && userId !== null && (
        <TopicEditor
          initial={topic}
          token={token}
          mode="edit"
          adminTargetUserId={userId}
          initialStep={initialStep}
          onCancel={() => navigate('/workbench/cockpit')}
          onSave={handleSave}
          onSaveDone={() => {
            // 保存后留在原页,刷新 topic 数据(让 stepper 更新画像/监测问题状态)
            adminReviewApi.getTopicReview(tid, token).then(setTopic).catch(() => {});
          }}
        />
      )}
    </div>
  );
}
