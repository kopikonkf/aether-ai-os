import { useMemo } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Grid,
  Message,
  Progress,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from '@arco-design/web-react';
import { Refresh, PlayOne, CheckOne, PauseOne } from '@icon-park/react';
import type { AetherFleetIncident, FleetJobKind } from '../../../common/aetherFleetTypes';
import { useAetherFleet } from './useAetherFleet';
import styles from './RuntimeOperations.module.css';

const { Title, Text } = Typography;
const { Row, Col } = Grid;

function severityColor(severity: string): 'red' | 'orange' | 'gold' | 'blue' {
  if (severity === 'critical') return 'red';
  if (severity === 'high') return 'orange';
  if (severity === 'warning') return 'gold';
  return 'blue';
}

export default function RuntimeOperationsPage() {
  const fleet = useAetherFleet();
  const snapshot = fleet.snapshot;
  const unresolved = useMemo(
    () => snapshot?.incidents.filter((item) => item.state !== 'resolved') ?? [],
    [snapshot],
  );

  async function decide(incident: AetherFleetIncident, state: 'acknowledged' | 'resolved') {
    const reason = state === 'acknowledged'
      ? 'Reviewed in AionUi runtime console'
      : 'Resolved by operator in AionUi runtime console';
    try {
      if (state === 'acknowledged') await fleet.acknowledgeIncident(incident.incident_id, reason);
      else await fleet.resolveIncident(incident.incident_id, reason);
      Message.success(`Incident ${state}`);
    } catch {
      // Hook exposes the operator-safe error state.
    }
  }

  if (!snapshot && fleet.loading) {
    return <div className={styles.page}><Spin dot tip="Loading Aether fleet state…" /></div>;
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Title heading={4}>Aether Runtime Operations</Title>
          <Text className={styles.muted}>Operator shell for backend-owned fleet governance.</Text>
        </div>
        <Space>
          <Button icon={<Refresh />} loading={fleet.loading} onClick={() => void fleet.refresh()}>Refresh</Button>
          <Button type="primary" icon={<PlayOne />} onClick={() => void fleet.runDue()}>Run due jobs</Button>
        </Space>
      </header>

      {fleet.error ? <Alert type="error" content={fleet.error} closable /> : null}

      {snapshot ? (
        <div className={styles.grid}>
          <Card title="Fleet state">
            <Tag color={snapshot.fleet_state === 'healthy' ? 'green' : snapshot.fleet_state === 'critical' ? 'red' : 'orange'}>
              {snapshot.fleet_state}
            </Tag>
            <div className={styles.metric}>{snapshot.routing_eligible_count}</div>
            <Text className={styles.muted}>routable drivers</Text>
          </Card>

          <Card title="Incidents">
            <div className={styles.metric}>{snapshot.open_incident_count}</div>
            <Text className={styles.muted}>{snapshot.critical_incident_count} critical</Text>
          </Card>

          <Card title="Invocation budget">
            <Progress
              percent={Math.min(100, (snapshot.budget.invocation_count / Math.max(1, snapshot.budget.invocation_limit)) * 100)}
              status={snapshot.budget.invocation_budget_exceeded ? 'error' : 'normal'}
            />
            <Text>{snapshot.budget.invocation_count} / {snapshot.budget.invocation_limit}</Text>
          </Card>

          <Card title="Known cost budget">
            <Progress
              percent={Math.min(100, (snapshot.budget.known_cost_usd / Math.max(0.01, snapshot.budget.cost_limit_usd)) * 100)}
              status={snapshot.budget.cost_budget_exceeded ? 'error' : 'normal'}
            />
            <Text>${snapshot.budget.known_cost_usd.toFixed(4)} / ${snapshot.budget.cost_limit_usd.toFixed(2)}</Text>
          </Card>

          <Card title="Drivers" className={styles.fullWidth}>
            <Row gutter={[12, 12]}>
              {snapshot.drivers.map((driver) => (
                <Col xs={24} md={12} xl={8} key={driver.driver_id}>
                  <Card size="small" title={driver.metadata?.display_name?.toString() ?? driver.driver_id}>
                    <Descriptions colon=" : " column={1} size="small" data={[
                      { label: 'Availability', value: driver.availability },
                      { label: 'Conformance', value: driver.conformance_state },
                      { label: 'Quota', value: driver.quota_state },
                      { label: 'Reliability', value: driver.reliability?.score?.toFixed(3) ?? 'unknown' },
                      { label: 'Routing', value: driver.routing_eligible ? 'eligible' : 'blocked' },
                    ]} />
                  </Card>
                </Col>
              ))}
            </Row>
          </Card>

          <Card title="Scheduled jobs" className={styles.fullWidth}>
            {snapshot.jobs.map((job) => (
              <div className={styles.row} key={job.job_id}>
                <div>
                  <Text bold>{job.kind}</Text><br />
                  <Text className={styles.muted}>Every {job.interval_seconds}s · next {job.next_run_at}</Text>
                </div>
                <div className={styles.actions}>
                  <Switch
                    checked={job.state === 'active'}
                    checkedIcon={<CheckOne />}
                    uncheckedIcon={<PauseOne />}
                    onChange={(enabled) => void fleet.updateJob(job.kind as FleetJobKind, { enabled })}
                  />
                  <Button size="small" onClick={() => void fleet.runJob(job.kind as FleetJobKind)}>Run</Button>
                </div>
              </div>
            ))}
          </Card>

          <Card title="Open incidents" className={styles.fullWidth}>
            {unresolved.length === 0 ? <Empty description="No open incidents" /> : unresolved.map((incident) => (
              <div className={styles.row} key={incident.incident_id}>
                <div>
                  <Space>
                    <Tag color={severityColor(incident.severity)}>{incident.severity}</Tag>
                    <Text bold>{incident.kind}</Text>
                  </Space>
                  <div><Text>{incident.summary}</Text></div>
                  <Text className={styles.muted}>Occurrences: {incident.occurrence_count}</Text>
                </div>
                <div className={styles.actions}>
                  {incident.state === 'open' ? (
                    <Button size="small" onClick={() => void decide(incident, 'acknowledged')}>Acknowledge</Button>
                  ) : null}
                  <Button size="small" type="primary" onClick={() => void decide(incident, 'resolved')}>Resolve</Button>
                </div>
              </div>
            ))}
          </Card>
        </div>
      ) : null}
    </main>
  );
}
