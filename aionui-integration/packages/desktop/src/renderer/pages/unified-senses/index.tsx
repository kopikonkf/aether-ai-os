import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Space, Spin, Tag, Typography } from '@arco-design/web-react';
import { CameraFive, Microphone, Refresh, Voice } from '@icon-park/react';
import styles from './UnifiedSenses.module.css';

type SenseStatus = {
  policy_id?: string;
  livekit?: { ready?: boolean; configured?: boolean; sdk_ready?: boolean };
  browser_requirements?: { secure_context?: boolean; permission_required?: boolean };
};

const UnifiedSensesPage: React.FC = () => {
  const [status, setStatus] = useState<SenseStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const sensesUrl = useMemo(() => '/senses', []);

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/browser-senses/status', { credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Aether Gateway returned ${response.status}`);
      setStatus((await response.json()) as SenseStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Typography.Text className={styles.eyebrow}>AETHER · UNIFIED SENSES</Typography.Text>
          <Typography.Title heading={3}>See. Hear. Speak.</Typography.Title>
          <Typography.Paragraph>
            Browser media is transported to Aether; identity, memory, cognition, and governance remain in Aether Gateway.
          </Typography.Paragraph>
        </div>
        <Button icon={<Refresh />} onClick={() => void refresh()} loading={loading}>Refresh</Button>
      </header>

      {error && <Alert type='warning' content={`Aether sidecar unavailable: ${error}`} />}

      <Space size='medium' wrap>
        <Card className={styles.capability}><Microphone size={22} /><span>Microphone</span></Card>
        <Card className={styles.capability}><Voice size={22} /><span>Speaker</span></Card>
        <Card className={styles.capability}><CameraFive size={22} /><span>Camera</span></Card>
        <Tag color={status?.livekit?.ready ? 'green' : 'orange'}>
          LiveKit {status?.livekit?.ready ? 'ready' : 'configuration required'}
        </Tag>
      </Space>

      <section className={styles.frameShell}>
        {loading && !status ? <Spin size={32} /> : (
          <iframe
            className={styles.frame}
            src={sensesUrl}
            title='Aether Unified Browser Senses'
            allow='microphone; camera; autoplay; display-capture'
          />
        )}
      </section>
    </main>
  );
};

export default UnifiedSensesPage;
