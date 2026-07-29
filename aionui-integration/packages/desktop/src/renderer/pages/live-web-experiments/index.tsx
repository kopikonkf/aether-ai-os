import { Alert, Button, Card, Empty, Message, Space, Spin, Tag, Typography } from '@arco-design/web-react';
import { ExperimentOne, Refresh, RadarThree, UpdateRotation } from '@icon-park/react';
import { useAetherExperiments } from './useAetherExperiments';
import styles from './LiveWebExperiments.module.css';
const { Title, Text } = Typography;
export default function LiveWebExperimentsPage(){
 const state=useAetherExperiments(); const data=state.snapshot;
 async function act(fn:()=>Promise<unknown>,message:string){try{await fn();Message.success(message)}catch{/* hook reports */}}
 if(!data&&state.loading)return <div className={styles.page}><Spin dot tip="Loading live web intelligence…"/></div>;
 return <main className={styles.page}><header className={styles.header}><div><Title heading={4}>Live Web Intelligence & Reversible Experiments</Title><Text className={styles.muted}>Observe broadly. Experiment reversibly. Escalate consequences.</Text></div><Space><Button icon={<RadarThree/>} onClick={()=>void act(()=>state.discover(),'Source discovery completed')}>Discover</Button><Button icon={<UpdateRotation/>} onClick={()=>void act(()=>state.refreshEvidence(),'Freshness evaluated')}>Freshness</Button><Button icon={<Refresh/>} loading={state.loading} onClick={()=>void state.refresh()}>Refresh</Button></Space></header>
 {state.error?<Alert type="error" content={state.error} closable/>:null}{data?<div className={styles.grid}>
 <Card title="Configured sources" className={styles.span4}><div className={styles.metric}>{data.web.sources.length}</div><Text className={styles.muted}>Exact configuration + conformance</Text></Card>
 <Card title="Experiment runs" className={styles.span4}><div className={styles.metric}>{data.experiments.runs.length}</div><Text className={styles.muted}>No-shell disposable workspaces</Text></Card>
 <Card title="Demand signals" className={styles.span4}><div className={styles.metric}>{data.experiments.signals.length}</div><Text className={styles.muted}>Synthetic remains separate</Text></Card>
 <Card title="Live source fleet" className={styles.span6}>{data.web.sources.map(source=><div className={styles.row} key={source.adapter_id}><div><Text bold>{source.adapter_id}</Text><div><Text className={styles.muted}>{source.endpoint}</Text></div></div><Space><Tag color={source.enabled?'green':'gray'}>{source.enabled?'enabled':'disabled'}</Tag><Button size="mini" onClick={()=>void act(()=>state.conform(source.adapter_id),'Conformance evaluated')}>Conform</Button></Space></div>)}</Card>
 <Card title="Reversible experiment runs" className={styles.span6}>{data.experiments.runs.length===0?<Empty description="No experiment runs"/>:data.experiments.runs.map(run=><div className={styles.row} key={run.run_id}><div><Space><ExperimentOne/><Text>{run.run_id}</Text></Space><Text className={styles.muted}>Cost ${Number(run.cost_usd).toFixed(2)}</Text></div><Space><Tag>{run.status}</Tag>{run.status==='ready'?<Button size="mini" onClick={()=>void act(()=>state.runPlan(run.plan_id),'Experiment executed')}>Run</Button>:null}</Space></div>)}</Card>
 <Card title="Responsibility boundary" className={styles.full}>{Object.entries(data.authority).map(([key,value])=><div className={styles.row} key={key}><Text>{key.replaceAll('_',' ')}</Text><Tag color={value?'green':'red'}>{String(value)}</Tag></div>)}</Card>
 </div>:null}</main>;
}
