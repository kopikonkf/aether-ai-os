import { Alert, Button, Card, Empty, Grid, Message, Space, Spin, Tag, Typography } from '@arco-design/web-react';
import { CheckOne, Refresh, Send, Telescope } from '@icon-park/react';
import { useAetherOpportunity } from './useAetherOpportunity';
import styles from './OpportunityIntelligence.module.css';
const { Title, Text } = Typography; const { Row, Col } = Grid; const money=(v?:number)=>`$${Number(v??0).toFixed(2)}`;
export default function OpportunityIntelligencePage(){
 const state=useAetherOpportunity(); const data=state.snapshot;
 async function act(fn:()=>Promise<unknown>,message:string){try{await fn();Message.success(message)}catch{/* hook reports */}}
 if(!data&&state.loading)return <div className={styles.page}><Spin dot tip="Loading opportunity intelligence…"/></div>;
 return <main className={styles.page}><header className={styles.header}><div><Title heading={4}>Aether Opportunity Intelligence</Title><Text className={styles.muted}>Explore freely. Experiment reversibly. Escalate consequences.</Text></div><Space><Button icon={<Telescope/>} onClick={()=>void act(()=>state.scout({objective:'AI business automation opportunity',queries:['automation agent'],source_kinds:['catalog'],autonomy_level:'observe'}),'Scout run completed')}>Run scout</Button><Button icon={<Refresh/>} loading={state.loading} onClick={()=>void state.refresh()}>Refresh</Button></Space></header>
 {state.error?<Alert type="error" content={state.error} closable/>:null}{data?<div className={styles.grid}>
 <Card title="Sources" className={styles.span4}><div className={styles.metric}>{data.sources.length}</div><Text className={styles.muted}>Health-probed capability mesh</Text></Card>
 <Card title="Evidence claims" className={styles.span4}><div className={styles.metric}>{Number(data.status.extracted_claims??0)}</div><Text className={styles.muted}>Provenance-bound; not direct knowledge</Text></Card>
 <Card title="Active mandates" className={styles.span4}><div className={styles.metric}>{data.mandates.filter(x=>x.status==='active').length}</div><Text className={styles.muted}>Progressive autonomy envelopes</Text></Card>
 <Card title="Opportunity portfolio" className={styles.full}>{data.candidates.length===0?<Empty description="No synthesized candidates"/>:data.candidates.map(item=><div className={styles.row} key={item.candidate_id}><div><Space><Text bold>{item.title}</Text><Tag color={item.status==='portfolio-ready'?'green':'orange'}>{item.status}</Tag><Tag>{item.category}</Tag></Space><div><Text>{item.problem_statement}</Text></div><Text className={styles.muted}>{item.supporting_source_ids.length} sources · {item.contradicting_claim_ids.length} contradictions · EV {money(item.score.expected_net_value_usd)}</Text></div><div className={styles.actions}><span className={styles.score}>{item.score.utility_score.toFixed(1)}</span>{item.status==='portfolio-ready'?<Button type="primary" icon={<CheckOne/>} onClick={()=>void act(()=>state.decide(item.candidate_id,{decision:'select',reason:'Reviewed independent evidence and bounded reversible experiment.',allocated_budget_usd:item.estimated_cost_usd}),'Candidate selected')}>Select</Button>:null}<Button icon={<Send/>} onClick={()=>void act(()=>state.convert(item.candidate_id),'Converted to mission brief')}>Mission</Button></div></div>)}</Card>
 <Card title="Source mesh" className={styles.span6}><Row gutter={[8,8]}>{data.sources.map(item=><Col span={24} key={item.adapter_id}><Space><Tag>{item.kind}</Tag><Text>{item.name}</Text></Space></Col>)}</Row></Card>
 <Card title="Responsibility ladder" className={styles.span6}>{Object.entries(data.authority).map(([key,value])=><div className={styles.row} key={key}><Text>{key.replaceAll('_',' ')}</Text><Tag>{String(value)}</Tag></div>)}</Card>
 </div>:null}</main>;
}
