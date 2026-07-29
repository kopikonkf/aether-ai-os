import { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Grid,
  Input,
  Message,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from '@arco-design/web-react';
import { CheckOne, CloseOne, Refresh, ViewGridDetail } from '@icon-park/react';
import type {
  AetherApprovalFilter,
  AetherApprovalStatus,
  AetherApprovalView,
} from '../../../common/aetherApprovalTypes';
import { useAetherApprovals } from './useAetherApprovals';
import styles from './ApprovalInbox.module.css';

const { Title, Text } = Typography;
const { Row, Col } = Grid;
const TextArea = Input.TextArea;
const Option = Select.Option;

const FILTERS: Array<{ value: AetherApprovalFilter; label: string }> = [
  { value: 'pending', label: 'Pending' },
  { value: 'executing', label: 'Executing' },
  { value: 'consumed', label: 'Consumed' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'expired', label: 'Expired' },
  { value: 'all', label: 'All' },
];

function statusColor(status: AetherApprovalStatus): 'blue' | 'green' | 'red' | 'orange' | 'gray' | 'purple' {
  if (status === 'pending') return 'orange';
  if (status === 'consumed') return 'green';
  if (status === 'approved' || status === 'executing') return 'blue';
  if (status === 'rejected') return 'red';
  if (status === 'expired') return 'gray';
  return 'purple';
}

function riskColor(risk: string): 'green' | 'gold' | 'orange' | 'red' {
  if (risk === 'critical') return 'red';
  if (risk === 'high') return 'orange';
  if (risk === 'medium') return 'gold';
  return 'green';
}

function readableTime(value?: string | null): string {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}

function ApprovalRow({ item, inspect }: { item: AetherApprovalView; inspect: (id: string) => void }) {
  return (
    <div className={styles.row}>
      <div className={styles.rowMain}>
        <Space wrap>
          <Text bold>{item.proposal.target}/{item.proposal.operation}</Text>
          <Tag color={statusColor(item.status)}>{item.status}</Tag>
          <Tag color={riskColor(item.proposal.risk)}>{item.proposal.risk}</Tag>
          <Tag>{item.proposal.reversible ? 'reversible' : 'irreversible'}</Tag>
        </Space>
        <div><Text>{item.proposal.reason || 'No reason supplied'}</Text></div>
        <Text className={styles.muted}>
          {item.proposal.target_hint ? `${item.proposal.target_hint} · ` : ''}
          expires {readableTime(item.expires_at)}
        </Text>
      </div>
      <Button icon={<ViewGridDetail />} onClick={() => inspect(item.approval_id)}>Inspect</Button>
    </div>
  );
}

export default function ApprovalInboxPage() {
  const [status, setStatus] = useState<AetherApprovalFilter>('pending');
  const [reason, setReason] = useState('');
  const approvals = useAetherApprovals(status);
  const snapshot = approvals.snapshot;
  const selected = approvals.selected;

  useEffect(() => setReason(''), [selected?.approval_id, selected?.status]);

  async function decide(approved: boolean) {
    if (!selected) return;
    const normalized = reason.trim();
    if (normalized.length < 3) {
      Message.warning('Enter a decision reason with at least 3 characters');
      return;
    }
    try {
      const receipt = await approvals.decide(approved, selected, normalized);
      Message.success(receipt.replayed
        ? 'Existing decision receipt replayed safely'
        : approved ? 'Action approved and resumed' : 'Action rejected');
      setReason('');
    } catch {
      // Hook exposes the operator-safe error state.
    }
  }

  if (!snapshot && approvals.loading) {
    return <div className={styles.page}><Spin dot tip="Loading approval authority…" /></div>;
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Title heading={4}>Aether Approval Inbox</Title>
          <Text className={styles.muted}>
            One governed queue. Exact action hash. One decision path across every surface.
          </Text>
        </div>
        <Space>
          <Select
            value={status}
            style={{ width: 150 }}
            onChange={(value) => {
              approvals.clearSelection();
              setStatus(value as AetherApprovalFilter);
            }}
          >
            {FILTERS.map((item) => <Option key={item.value} value={item.value}>{item.label}</Option>)}
          </Select>
          <Button icon={<Refresh />} loading={approvals.loading} onClick={() => void approvals.refresh()}>
            Refresh
          </Button>
        </Space>
      </header>

      {approvals.error ? <Alert type="error" content={approvals.error} closable /> : null}

      {snapshot ? (
        <>
          <Row gutter={[12, 12]} className={styles.metrics}>
            <Col xs={12} md={6}><Card title="Pending"><div className={styles.metric}>{snapshot.status_counts.pending}</div></Card></Col>
            <Col xs={12} md={6}><Card title="Executing"><div className={styles.metric}>{snapshot.status_counts.executing}</div></Card></Col>
            <Col xs={12} md={6}><Card title="Consumed"><div className={styles.metric}>{snapshot.status_counts.consumed}</div></Card></Col>
            <Col xs={12} md={6}><Card title="Rejected / expired"><div className={styles.metric}>{snapshot.status_counts.rejected + snapshot.status_counts.expired}</div></Card></Col>
          </Row>

          <div className={styles.workspace}>
            <Card title={`${FILTERS.find((item) => item.value === status)?.label ?? status} approvals`} className={styles.queue}>
              {snapshot.approvals.length === 0
                ? <Empty description={`No ${status} approvals`} />
                : snapshot.approvals.map((item) => (
                  <ApprovalRow key={item.approval_id} item={item} inspect={(id) => void approvals.inspect(id)} />
                ))}
            </Card>

            <Card title="Approval detail" className={styles.detail}>
              {!selected ? <Empty description="Select an approval to inspect its bounded projection" /> : (
                <div className={styles.detailBody}>
                  <Space wrap>
                    <Tag color={statusColor(selected.status)}>{selected.status}</Tag>
                    <Tag color={riskColor(selected.proposal.risk)}>{selected.proposal.risk}</Tag>
                    {selected.proposal.required_scopes.map((scope) => <Tag key={scope}>{scope}</Tag>)}
                  </Space>

                  <Descriptions
                    colon=" : "
                    column={1}
                    size="small"
                    data={[
                      { label: 'Action', value: `${selected.proposal.target}/${selected.proposal.operation}` },
                      { label: 'Reason', value: selected.proposal.reason || '—' },
                      { label: 'Target hint', value: selected.proposal.target_hint || 'withheld' },
                      { label: 'Argument keys', value: selected.proposal.argument_keys.join(', ') || 'none' },
                      { label: 'Reversible', value: selected.proposal.reversible ? 'yes' : 'no' },
                      { label: 'Requested', value: readableTime(selected.requested_at) },
                      { label: 'Expires', value: readableTime(selected.expires_at) },
                      { label: 'Request channel', value: selected.request_channel || 'unknown' },
                      { label: 'Requested by', value: selected.requested_by || 'unknown' },
                    ]}
                  />

                  <div className={styles.hashBlock}>
                    <Text className={styles.muted}>Exact action SHA-256</Text>
                    <Text code copyable>{selected.action_hash}</Text>
                  </div>

                  {Object.keys(selected.proposal.context).length > 0 ? (
                    <div>
                      <Text bold>Bounded context</Text>
                      {Object.entries(selected.proposal.context).map(([key, value]) => (
                        <div className={styles.contextRow} key={key}>
                          <Text className={styles.muted}>{key}</Text><Text>{value}</Text>
                        </div>
                      ))}
                    </div>
                  ) : null}

                  {selected.result ? (
                    <Alert
                      type={selected.result.ok ? 'success' : 'error'}
                      content={`${selected.result.status}${selected.result.error ? `: ${selected.result.error}` : ''}`}
                    />
                  ) : null}

                  {selected.status === 'pending' ? (
                    <div className={styles.decision}>
                      <TextArea
                        value={reason}
                        onChange={setReason}
                        maxLength={500}
                        showWordLimit
                        autoSize={{ minRows: 3, maxRows: 6 }}
                        placeholder="Why should this exact action be approved or rejected?"
                      />
                      <Space>
                        <Button
                          type="primary"
                          icon={<CheckOne />}
                          loading={approvals.loading}
                          disabled={reason.trim().length < 3}
                          onClick={() => void decide(true)}
                        >
                          Approve exact action
                        </Button>
                        <Button
                          status="danger"
                          icon={<CloseOne />}
                          loading={approvals.loading}
                          disabled={reason.trim().length < 3}
                          onClick={() => void decide(false)}
                        >
                          Reject
                        </Button>
                      </Space>
                    </div>
                  ) : (
                    <Descriptions
                      colon=" : "
                      column={1}
                      size="small"
                      data={[
                        { label: 'Decided by', value: selected.decided_by || '—' },
                        { label: 'Decision reason', value: selected.decision_reason || '—' },
                        { label: 'Decision time', value: readableTime(selected.decided_at) },
                        { label: 'Consumed time', value: readableTime(selected.consumed_at) },
                      ]}
                    />
                  )}
                </div>
              )}
            </Card>
          </div>

          <Alert
            type="info"
            content="The renderer receives no operator token, raw action body, secret values, or result output. Gateway governance remains the execution authority."
          />
        </>
      ) : null}
    </main>
  );
}
