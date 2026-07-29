import { useMemo } from 'react';
import { Alert, Button, Card, Empty, Grid, Message, Space, Spin, Tag, Typography } from '@arco-design/web-react';
import { CheckOne, PauseOne, PlayOne, Refresh, CloseOne } from '@icon-park/react';
import { useAetherMissions } from './useAetherMissions';
import styles from './MissionOperations.module.css';

const { Title, Text } = Typography;
const { Row, Col } = Grid;
const money = (value?: number) => `$${Number(value ?? 0).toFixed(2)}`;

export default function MissionOperationsPage() {
  const missions = useAetherMissions();
  const snapshot = missions.snapshot;
  const totals = useMemo(() => (snapshot?.missions ?? []).reduce((acc, item) => {
    acc.claimed += item.outcome?.claimed_value_usd ?? 0;
    acc.realized += item.outcome?.realized_revenue_usd ?? 0;
    acc.verified += item.outcome?.verified_revenue_usd ?? 0;
    return acc;
  }, { claimed: 0, realized: 0, verified: 0 }), [snapshot]);

  async function act(operation: () => Promise<unknown>, message: string) {
    try { await operation(); Message.success(message); } catch { /* Hook exposes safe error. */ }
  }

  if (!snapshot && missions.loading) return <div className={styles.page}><Spin dot tip="Loading Aether missions…" /></div>;
  return <main className={styles.page}>
    <header className={styles.header}>
      <div><Title heading={4}>Aether Mission Operations</Title><Text className={styles.muted}>Evidence-first opportunity review and bounded mission execution.</Text></div>
      <Button icon={<Refresh />} loading={missions.loading} onClick={() => void missions.refresh()}>Refresh</Button>
    </header>
    {missions.error ? <Alert type="error" content={missions.error} closable /> : null}
    {snapshot ? <div className={styles.grid}>
      <Card title="Claimed value" className={styles.span4}><div className={styles.metric}>{money(totals.claimed)}</div><Text className={styles.muted}>Hypothesis only; not revenue.</Text></Card>
      <Card title="Realized revenue" className={styles.span4}><div className={styles.metric}>{money(totals.realized)}</div><Text className={styles.muted}>External evidence recorded.</Text></Card>
      <Card title="Verified revenue" className={styles.span4}><div className={styles.metric}>{money(totals.verified)}</div><Text className={styles.muted}>Founder/operator verified.</Text></Card>
      <Card title="Opportunity briefs" className={styles.full}>
        {snapshot.opportunities.length === 0 ? <Empty description="No opportunity briefs" /> : <Row gutter={[12, 12]}>{snapshot.opportunities.map((brief) => <Col xs={24} lg={12} key={brief.brief_id}><Card size="small" title={brief.title} extra={<Tag color={brief.blockers.length ? 'orange' : 'green'}>{brief.blockers.length ? 'blocked' : 'reviewable'}</Tag>}><Text>{brief.problem_statement}</Text><div><Text className={styles.muted}>EV {money(brief.expected_net_value_usd)} · {brief.independent_support_count} independent sources · {brief.contradiction_evidence_ids.length} contradictions</Text></div></Card></Col>)}</Row>}
      </Card>
      <Card title="Mission queue" className={styles.full}>
        {snapshot.missions.length === 0 ? <Empty description="No missions" /> : snapshot.missions.map((item) => <div className={styles.row} key={item.plan.mission_id}>
          <div><Space><Text bold>{item.plan.objective}</Text><Tag>{item.status}</Tag></Space><div><Text className={styles.muted}>{item.plan.northstar_alignment}</Text></div><Text className={styles.muted}>{item.plan.steps.length} steps · budget {money(item.plan.budget.max_cost_usd)}</Text></div>
          <div className={styles.actions}>
            {item.status === 'review-required' ? <><Button type="primary" icon={<CheckOne />} onClick={() => void act(() => missions.approve(item.plan.mission_id, 'Reviewed in native AionUi mission console'), 'Mission approved')}>Approve</Button><Button status="danger" icon={<CloseOne />} onClick={() => void act(() => missions.reject(item.plan.mission_id, 'Rejected in native AionUi mission console'), 'Mission rejected')}>Reject</Button></> : null}
            {['approved', 'paused', 'waiting-approval', 'running'].includes(item.status) ? <><Button type="primary" icon={<PlayOne />} onClick={() => void act(() => missions.run(item.plan.mission_id), 'Mission advanced')}>Run / Resume</Button><Button icon={<PauseOne />} onClick={() => void act(() => missions.pause(item.plan.mission_id, 'Paused in native AionUi mission console'), 'Mission paused')}>Pause</Button></> : null}
          </div>
        </div>)}
      </Card>
    </div> : null}
  </main>;
}
