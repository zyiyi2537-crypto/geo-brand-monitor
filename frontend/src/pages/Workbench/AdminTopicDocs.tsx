// 项目内「文案」页 — stepper step 3 落地,套壳 AdminContentReview 锁定到当前 topic.
// 路由:/workbench/topics/:topicId/docs

import { useParams } from 'react-router-dom';
import { PageHead } from '../../components/PageHead';
import { TopicStepper } from '../../components/TopicStepper';
import { AdminContentReview } from '../Admin/ContentReview';

export function AdminTopicDocs() {
  const { topicId } = useParams();
  const tid = Number(topicId);

  return (
    <div className="space-y-4">
      <PageHead titleKey="workbench.topicStepper.docs" titleFallback="文案" />
      <TopicStepper topicId={tid} active="docs" />
      <AdminContentReview lockedTopicId={tid} />
    </div>
  );
}
