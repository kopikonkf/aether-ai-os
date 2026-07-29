const $ = (id) => document.getElementById(id);
const state = {
  room:null,
  localStream:null,
  browserToken:'',
  session:null,
  livekit:null,
  micEnabled:false,
  cameraEnabled:false,
  autoVisionTimer:null,
  fallbackRecognition:null,
  voices:[],
  voiceProfile:{name:'__auto__',lang:'id-ID',rate:1.02,pitch:1.12,volume:1}
};
const API = '';

function message(role, text){const node=document.createElement('div');node.className=`message ${role}`;node.textContent=text;$('messages').appendChild(node);$('messages').scrollTop=$('messages').scrollHeight;}
function setState(online, text){$('systemState').className=`pill ${online?'online':'offline'}`;$('systemState').textContent=online?'CONNECTED':'OFFLINE';$('transportStatus').textContent=text;}
async function jsonFetch(url, options={}){const response=await fetch(url,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});let data={};try{data=await response.json();}catch{}if(!response.ok)throw new Error(data.detail?.message||data.detail||data.error||`${response.status} ${response.statusText}`);return data;}
function authHeaders(){return {Authorization:`Bearer ${state.browserToken}`};}
async function reportTrack(track_sid,kind,source,muted=false){if(!state.browserToken)return;try{await jsonFetch(`${API}/api/browser-senses/tracks`,{method:'POST',headers:authHeaders(),body:JSON.stringify({track_sid,kind,source,muted})});}catch(error){message('system',`Track receipt failed: ${error.message}`);}}

function loadVoiceProfile(){ /* Voice preferences are session-only; operator tokens and preferences are not persisted. */ }

function voiceScore(voice){
  const name=voice.name.toLowerCase();
  const lang=(voice.lang||'').toLowerCase();
  let score=0;
  if(lang==='id-id')score+=120;
  else if(lang.startsWith('id'))score+=100;
  if(name.includes('microsoft gadis'))score+=100;
  if(name.includes('aoede'))score+=95;
  if(name.includes('google')&&name.includes('bahasa indonesia'))score+=90;
  if(/female|woman|gadis|zira|aria|jenny|natasha|siti|damayanti|catherine|samantha/.test(name))score+=55;
  if(/male|pria|david|mark|guy/.test(name))score-=80;
  if(voice.localService)score+=5;
  return score;
}

function refreshVoiceList(){
  if(!('speechSynthesis' in window))return;
  state.voices=speechSynthesis.getVoices().slice().sort((a,b)=>voiceScore(b)-voiceScore(a)||a.name.localeCompare(b.name));
  const select=$('voiceSelect');
  if(!select)return;
  select.innerHTML='';
  const autoOption=document.createElement('option');
  autoOption.value='__auto__';
  autoOption.textContent='Aether chooses automatically';
  select.appendChild(autoOption);
  for(const voice of state.voices){
    const option=document.createElement('option');
    option.value=voice.name;
    option.textContent=`${voice.name} (${voice.lang})${voice.default?' — default':''}`;
    select.appendChild(option);
  }
  const saved=state.voices.find(v=>v.name===state.voiceProfile.name);
  if(state.voiceProfile.name==='__auto__'){select.value='__auto__';}
  else if(saved){state.voiceProfile.lang=saved.lang||'id-ID';select.value=saved.name;}
  else{state.voiceProfile.name='__auto__';select.value='__auto__';}
  updateVoiceLabels();
}

function updateVoiceLabels(){
  if($('voiceRateValue'))$('voiceRateValue').textContent=Number(state.voiceProfile.rate).toFixed(2);
  if($('voicePitchValue'))$('voicePitchValue').textContent=Number(state.voiceProfile.pitch).toFixed(2);
}

function saveVoiceProfile(){ updateVoiceLabels(); }

function extractSpeechText(text){
  const raw=String(text||'');
  return raw
    .replace(/\[(?:TOOL|WRITE)[^\]]*\][\s\S]*?\[\/(?:TOOL|WRITE)\]/gi,'')
    .replace(/<[^>]+>/g,' ')
    .replace(/\[(?:VOICE|\/VOICE)\]/gi,'')
    .replace(/[`*_#>]/g,' ')
    .replace(/\s+/g,' ')
    .trim();
}

function chooseAutomaticVoice(spoken){
  if(!state.voices.length)return null;
  const feminine=state.voices.filter(voice=>voiceScore(voice)>20);
  const pool=feminine.length?feminine:state.voices;
  const normalized=String(spoken||'').toLowerCase();
  let offset=0;
  if(/selamat|berhasil|great|keren|yay|haha|wkwk/.test(normalized))offset=1;
  else if(/tenang|refleksi|maaf|khawatir|pelan/.test(normalized))offset=2;
  else if(/bisnis|revenue|strategi|keputusan|risiko/.test(normalized))offset=3;
  return pool[Math.min(offset,pool.length-1)]||pool[0];
}

function speak(text){
  if(!('speechSynthesis' in window))return;
  const spoken=extractSpeechText(text);
  if(!spoken)return;
  const utterance=new SpeechSynthesisUtterance(spoken);
  const selected=state.voiceProfile.name==='__auto__'?chooseAutomaticVoice(spoken):(state.voices.find(voice=>voice.name===state.voiceProfile.name)||state.voices[0]);
  if(selected){utterance.voice=selected;utterance.lang=selected.lang||state.voiceProfile.lang;}
  else{utterance.lang=state.voiceProfile.lang||'id-ID';}
  utterance.rate=Number(state.voiceProfile.rate)||1.02;
  utterance.pitch=Number(state.voiceProfile.pitch)||1.12;
  utterance.volume=Number(state.voiceProfile.volume)||1;
  speechSynthesis.cancel();
  speechSynthesis.speak(utterance);
}

function previewVoice(){
  speak('[VOICE]Halo, Dee. Aku Aether. Suara ini akan menjadi suara browser senses-ku.[/VOICE]');
}

async function issueSession(){const operatorToken=$('operatorToken').value.trim();if(!operatorToken)throw new Error('Founder/operator token is required.');const result=await jsonFetch(`${API}/api/browser-senses/session`,{method:'POST',headers:{'X-Aether-Operator-Token':operatorToken},body:JSON.stringify({display_name:$('displayName').value.trim()||'Founder',capabilities:['text','microphone','speaker','camera'],ttl_seconds:3600})});state.browserToken=result.browser_session_token;state.session=result.session;state.livekit=result.livekit;$('sessionLabel').textContent=result.session.session_id;message('system',`Session ${result.session.session_id} issued. LiveKit ${result.livekit.ready?'ready':'unavailable'}.`);return result;}

async function connectLiveKit(){if(!state.livekit?.ready)throw new Error(state.livekit?.error||'LiveKit transport is not ready.');const livekit=await import('https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/+esm');const room=new livekit.Room({adaptiveStream:true,dynacast:true});room.on(livekit.RoomEvent.TrackSubscribed,(track)=>{if(track.kind===livekit.Track.Kind.Audio){const el=track.attach();el.autoplay=true;$('remoteAudio').appendChild(el);}if(track.kind===livekit.Track.Kind.Video){track.attach($('localVideo'));}});room.on(livekit.RoomEvent.TranscriptionReceived,(segments)=>{const final=segments.filter(s=>s.final).map(s=>s.text).join(' ');if(final){$('transcript').textContent=final;message('user',final);}});room.on(livekit.RoomEvent.Disconnected,()=>setState(false,'LiveKit disconnected.'));await room.connect(state.livekit.server_url,state.livekit.participant_token);state.room=room;await room.localParticipant.setMicrophoneEnabled(true);state.micEnabled=true;await reportTrack('browser-microphone','audio','microphone',false);$('micButton').disabled=false;$('disconnectButton').disabled=false;$('fallbackTalk').disabled=false;$('voiceState').textContent='LiveKit voice active';$('orb').classList.add('active');await jsonFetch(`${API}/api/browser-senses/session/active`,{method:'POST',headers:authHeaders(),body:JSON.stringify({transport:'livekit'})});setState(true,'LiveKit microphone/speaker connected. Aether Gateway owns cognition.');}

async function connect(){try{$('connectButton').disabled=true;await issueSession();if(state.livekit?.ready){await connectLiveKit();}else{$('fallbackTalk').disabled=false;$('disconnectButton').disabled=false;setState(true,'Aether session active; LiveKit unavailable. Text and browser STT fallback remain available.');}}catch(error){message('system',`Connect failed: ${error.message}`);setState(false,error.message);$('connectButton').disabled=false;}}

async function ensureCamera(){if(state.cameraEnabled)return;const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:1280},height:{ideal:720}},audio:false});state.localStream=stream;$('localVideo').srcObject=stream;state.cameraEnabled=true;await reportTrack(stream.getVideoTracks()[0]?.id||'browser-camera','video','camera',false);$('cameraState').textContent='camera active';$('cameraButton').textContent='Disable camera';$('visionButton').disabled=!state.browserToken;if(state.room){const track=stream.getVideoTracks()[0];const livekit=await import('https://cdn.jsdelivr.net/npm/livekit-client@2.17.2/+esm');const localTrack=new livekit.LocalVideoTrack(track);await state.room.localParticipant.publishTrack(localTrack);}}
async function toggleCamera(){try{if(!state.cameraEnabled){await ensureCamera();}else{state.localStream?.getTracks().forEach(t=>t.stop());state.localStream=null;state.cameraEnabled=false;$('localVideo').srcObject=null;$('cameraState').textContent='camera off';$('cameraButton').textContent='Enable camera';$('visionButton').disabled=true;stopAutoVision();}}catch(error){message('system',`Camera failed: ${error.message}`);}}
function captureFrame(){const video=$('localVideo');if(!video.videoWidth)throw new Error('Camera frame is not ready.');const canvas=$('frameCanvas');const maxWidth=960;const scale=Math.min(1,maxWidth/video.videoWidth);canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);const dataUrl=canvas.toDataURL('image/jpeg',0.72);return {data_base64:dataUrl.split(',')[1],content_type:'image/jpeg',width:canvas.width,height:canvas.height,prompt:$('visionPrompt').value.trim()};}
async function askVision(silent=false){if(!state.browserToken)throw new Error('Connect a browser session first.');$('visionBadge').textContent='VISION THINKING';try{const result=await jsonFetch(`${API}/api/browser-senses/vision`,{method:'POST',headers:authHeaders(),body:JSON.stringify(captureFrame())});$('visionBadge').textContent='VISION READY';if(!silent)message('user','[camera frame]');message('assistant',result.response);$('transcript').textContent=result.response;if(!state.room){speak(result.response);}}catch(error){$('visionBadge').textContent='VISION ERROR';message('system',`Vision failed: ${error.message}`);}}
function stopAutoVision(){clearInterval(state.autoVisionTimer);state.autoVisionTimer=null;$('autoVision').checked=false;}
function toggleAutoVision(){if(!$('autoVision').checked){stopAutoVision();return;}if(!state.cameraEnabled||!state.browserToken){$('autoVision').checked=false;message('system','Connect and enable camera before bounded vision.');return;}state.autoVisionTimer=setInterval(()=>askVision(true),15000);message('system','Bounded vision enabled: one keyframe every 15 seconds.');}
async function sendText(text){if(!state.browserToken)throw new Error('Connect a browser session first.');message('user',text);$('transcript').textContent=text;const result=await jsonFetch(`${API}/api/browser-senses/text`,{method:'POST',headers:authHeaders(),body:JSON.stringify({text})});message('assistant',result.response);$('transcript').textContent=result.response;if(!state.room){speak(result.response);}}
function fallbackSTT(){const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;if(!Recognition){message('system','Browser SpeechRecognition is unavailable. Use LiveKit or text input.');return;}const recognition=new Recognition();recognition.lang=navigator.language||'id-ID';recognition.interimResults=true;recognition.continuous=false;recognition.onresult=(event)=>{let text='';for(let i=event.resultIndex;i<event.results.length;i++)text+=event.results[i][0].transcript;$('transcript').textContent=text;if(event.results[event.results.length-1].isFinal)sendText(text.trim());};recognition.onerror=(event)=>message('system',`Browser STT error: ${event.error}`);recognition.start();state.fallbackRecognition=recognition;}
async function toggleMic(){if(!state.room)return;state.micEnabled=!state.micEnabled;await state.room.localParticipant.setMicrophoneEnabled(state.micEnabled);await reportTrack('browser-microphone','audio','microphone',!state.micEnabled);$('micButton').textContent=state.micEnabled?'Mute microphone':'Unmute microphone';$('voiceState').textContent=state.micEnabled?'LiveKit voice active':'microphone muted';}
async function disconnect(){stopAutoVision();state.localStream?.getTracks().forEach(t=>t.stop());state.localStream=null;if(state.room)await state.room.disconnect();if(state.browserToken){try{await jsonFetch(`${API}/api/browser-senses/session/close`,{method:'POST',headers:authHeaders(),body:JSON.stringify({reason:'browser-disconnect'})});}catch{}}state.room=null;state.browserToken='';state.session=null;state.livekit=null;state.micEnabled=false;state.cameraEnabled=false;$('connectButton').disabled=false;$('micButton').disabled=true;$('fallbackTalk').disabled=true;$('disconnectButton').disabled=true;$('visionButton').disabled=true;$('orb').classList.remove('active');$('voiceState').textContent='not started';$('cameraState').textContent='not started';$('sessionLabel').textContent='no session';setState(false,'Disconnected.');}

loadVoiceProfile();
$('voiceRate').value=state.voiceProfile.rate;
$('voicePitch').value=state.voiceProfile.pitch;
refreshVoiceList();
if('speechSynthesis' in window){speechSynthesis.addEventListener?.('voiceschanged',refreshVoiceList);speechSynthesis.onvoiceschanged=refreshVoiceList;}
$('voiceSelect').addEventListener('change',(event)=>{const selected=state.voices.find(voice=>voice.name===event.target.value);state.voiceProfile.name=event.target.value;if(selected)state.voiceProfile.lang=selected.lang;saveVoiceProfile();});
$('voiceRate').addEventListener('input',(event)=>{state.voiceProfile.rate=Number(event.target.value);saveVoiceProfile();});
$('voicePitch').addEventListener('input',(event)=>{state.voiceProfile.pitch=Number(event.target.value);saveVoiceProfile();});
$('previewVoice').addEventListener('click',previewVoice);
$('connectButton').addEventListener('click',connect);$('disconnectButton').addEventListener('click',disconnect);$('micButton').addEventListener('click',toggleMic);$('fallbackTalk').addEventListener('click',fallbackSTT);$('cameraButton').addEventListener('click',toggleCamera);$('visionButton').addEventListener('click',()=>askVision(false));$('autoVision').addEventListener('change',toggleAutoVision);$('chatForm').addEventListener('submit',async(event)=>{event.preventDefault();const text=$('chatInput').value.trim();if(!text)return;$('chatInput').value='';try{await sendText(text);}catch(error){message('system',error.message);}});window.addEventListener('beforeunload',()=>{state.room?.disconnect();state.localStream?.getTracks().forEach(t=>t.stop());});
if(!window.isSecureContext){message('system','This page is not a secure context. Microphone and camera require HTTPS or localhost.');}
