import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowUpRight, CalendarDays, Check, ChevronDown, Clock3, HeartPulse, Mic, MicOff, Phone, PhoneOff, Plus, Search, ShieldCheck, Sparkles, Stethoscope, UserRound, UsersRound, Volume2, X} from 'lucide-react';
import {PipecatClient} from '@pipecat-ai/client-js';
import {SmallWebRTCTransport} from '@pipecat-ai/small-webrtc-transport';
import './style.css';

// The voice server also serves the dashboard API; set VITE_API_URL to use a
// standalone API (e.g. uvicorn backend.main:app on :8000) instead.
const API = import.meta.env.VITE_API_URL || import.meta.env.VITE_VOICE_URL || 'http://localhost:7860';
const VOICE = import.meta.env.VITE_VOICE_URL || 'http://localhost:7860';
const initials = n => n.split(' ').slice(1).map(x=>x[0]).join('').replace('.','');
const niceDate = d => new Date(d+'T12:00:00').toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short'});
function App(){
 const [doctors,setDoctors]=useState([]),[appointments,setAppointments]=useState([]),[health,setHealth]=useState(null),[filter,setFilter]=useState('All'),[query,setQuery]=useState(''),[call,setCall]=useState(false),[muted,setMuted]=useState(false),[elapsed,setElapsed]=useState(0),[messages,setMessages]=useState([]),[status,setStatus]=useState('idle'),[audioStatus,setAudioStatus]=useState('Waiting for assistant audio…');
 const client=useRef(null),audioRef=useRef(null),timer=useRef(null),transcriptRef=useRef(null),mutedRef=useRef(false),botSpeakingRef=useRef(false);
 const refresh=async()=>{try{const [d,a,h]=await Promise.all([fetch(API+'/api/doctors').then(r=>r.json()),fetch(API+'/api/appointments').then(r=>r.json()),fetch(API+'/api/health').then(r=>r.json())]);setDoctors(d);setAppointments(a);setHealth(h)}catch{setHealth({status:'offline',voice_configured:false})}};
 useEffect(()=>{refresh();const id=setInterval(refresh,5000);return()=>clearInterval(id)},[]);
 useEffect(()=>{if(call){timer.current=setInterval(()=>setElapsed(s=>s+1),1000)}else clearInterval(timer.current);return()=>clearInterval(timer.current)},[call]);
 useEffect(()=>{transcriptRef.current?.scrollTo(0,transcriptRef.current.scrollHeight)},[messages]);
 const maskPhone=p=>{const d=(p||'').replace(/\D/g,'');return d.length>4?`••• ${d.slice(-4)}`:d};
 const fmt=n=>`${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;
 const startCall=async()=>{setCall(true);setElapsed(0);setMessages([]);setAudioStatus('Waiting for assistant audio…');setStatus('connecting');try{
   const t=new SmallWebRTCTransport(); const c=new PipecatClient({transport:t,enableMic:true});client.current=c;
   // 'connected' is only the WebRTC link; wait until the pipeline is running.
   c.on('botReady',()=>{setStatus('connected')});
   c.on('disconnected',()=>{setStatus('ended');botSpeakingRef.current=false});
   // The mic stays open while the assistant speaks: the browser's echo
   // cancellation keeps its voice out of the mic, and the caller can barge in.
   // (Toggling enableMic here stops/restarts the mic track and could leave it
   // dead after the assistant finished speaking.)
   c.on('botStartedSpeaking',()=>{botSpeakingRef.current=true});
   c.on('botStoppedSpeaking',()=>{botSpeakingRef.current=false});
   // STT finalizes a chunk at every short pause, but the server keeps
   // collecting until the caller's whole turn is done. Mirror that: everything
   // the caller says until Careline replies stays in one row. `base` holds the
   // finalized chunks; the interim (still-changing) chunk is appended to it.
   c.on('userTranscript',data=>{if(data?.text)setMessages(m=>{
     const last=m[m.length-1];
     const join=(a,b)=>a?`${a} ${b}`:b;
     if(last?.role==='user'){
       const base=data.final?join(last.base,data.text):last.base;
       return [...m.slice(0,-1),{role:'user',base,text:data.final?base:join(last.base,data.text)}];
     }
     return [...m,{role:'user',base:data.final?data.text:'',text:data.text}];
   })});
   // One spoken sentence emits several botOutput events (new → in-progress →
   // completed) with the same segment_id. Update that sentence's row in
   // place instead of appending a duplicate for every event.
   c.on('botOutput',data=>{if(data?.text)setMessages(m=>{
     const seg=data.segment_id;
     const i=seg==null?-1:m.findIndex(x=>x.role==='assistant'&&x.seg===seg);
     if(i>=0){const copy=m.slice();copy[i]={...copy[i],text:data.text};return copy}
     const last=m[m.length-1];
     if(seg==null&&last?.role==='assistant'&&last.text===data.text)return m;
     return [...m,{role:'assistant',text:data.text,seg}];
   })});
   // trackStarted also fires for the local mic (again each time the mic is
   // re-enabled); only attach the bot's remote track to the speaker.
   c.on('trackStarted',(track,participant)=>{if(track.kind==='audio'&&!participant?.local&&audioRef.current){setAudioStatus('Assistant audio track received');audioRef.current.srcObject=new MediaStream([track]);audioRef.current.play().then(()=>setAudioStatus('Assistant audio playing')).catch(e=>{setAudioStatus(`Audio playback blocked (${e.name})`);console.error('Audio playback failed',e)})}});
   await c.connect({webrtcUrl:VOICE+'/api/offer'});
  }catch(e){setStatus('error');setMessages(m=>[...m,{role:'assistant',text:'Could not connect. Start the Pipecat voice server and check your API keys and microphone permission.'}]);console.error(e)}};
 const endCall=async()=>{try{await client.current?.disconnect()}catch{} client.current=null;botSpeakingRef.current=false;mutedRef.current=false;setCall(false);setStatus('ended');setMuted(false);refresh()};
 const toggleMute=()=>{const next=!muted;mutedRef.current=next;setMuted(next);try{client.current?.enableMic(!next)}catch{}};
 const retryAudio=()=>audioRef.current?.play().then(()=>setAudioStatus('Assistant audio playing')).catch(()=>{});
 const specialties=['All',...new Set(doctors.map(d=>d.specialty))];
 const filtered=doctors.filter(d=>(filter==='All'||d.specialty===filter)&&d.name.toLowerCase().includes(query.toLowerCase()));
 const allSlots=doctors.reduce((n,d)=>n+d.slots.length,0);
 return <div className="shell">
  <aside className="sidebar"><div className="brand"><div className="brandmark"><HeartPulse size={19}/></div><span>careline<span className="branddot">.</span></span></div>
   <div className="navlabel">WORKSPACE</div><div className="navitem active"><Activity size={17}/> Overview <span className="navrail"/></div><div className="navitem"><CalendarDays size={17}/> Appointments</div><div className="navitem"><Stethoscope size={17}/> Care team</div>
   <div className="side-bottom"><div className="online-card"><span className="pulse-dot"/><div><b>Clinic is online</b><small>Taking appointments</small></div><ChevronDown size={15}/></div><div className="profile"><div className="profile-avatar">CD</div><div className="profile-info"><b>Clinic dashboard</b><small>Careline Health</small></div><span className="more">···</span></div></div>
  </aside>
  <main className="main"><header className="topbar"><div className="crumb">Workspace <span>/</span> Overview</div><div className="top-right"><div className="status-pill"><i/> {health?.status==='online'?'All systems operational':'API unavailable'}</div><div className="top-avatar">CD</div></div></header>
   <section className="intro"><div><div className="eyebrow"><span className="eyebrow-line"/> {new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'}).toUpperCase()}</div><h1>A calmer way to care.</h1><p>Your clinic at a glance. Start a call or manage today’s care.</p></div><button className="call-cta" onClick={startCall}><Phone size={16} fill="currentColor"/> Try a voice call <ArrowUpRight size={15}/></button></section>
   <section className="stats"><article className="stat-card"><div className="stat-top"><span>Available appointments</span><span className="stat-icon mint"><CalendarDays size={16}/></span></div><div className="stat-num">{allSlots}<small>slots</small></div><div className="stat-foot"><i className="tiny-green"/> Across the next 5 days</div></article><article className="stat-card"><div className="stat-top"><span>Appointments booked</span><span className="stat-icon lilac"><UsersRound size={16}/></span></div><div className="stat-num">{appointments.filter(a=>a.status==='booked').length}<small>active</small></div><div className="stat-foot muted-foot">Live from your appointment list</div></article><article className="stat-card"><div className="stat-top"><span>Care team</span><span className="stat-icon peach"><Stethoscope size={16}/></span></div><div className="stat-num">{doctors.length}<small>doctors</small></div><div className="stat-foot muted-foot">Across {specialties.length-1} specialties</div></article></section>
   <section className="content-grid"><div className="panel doctors-panel"><div className="panel-head"><div><div className="section-kicker">YOUR CARE TEAM</div><h2>Doctors & availability</h2></div><button className="subtle-btn" onClick={()=>setQuery('')}><Plus size={15}/> View all</button></div><div className="filterrow"><div className="searchbox"><Search size={15}/><input placeholder="Find a doctor" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="filters">{specialties.map(s=><button className={filter===s?'selected':''} onClick={()=>setFilter(s)} key={s}>{s}</button>)}</div></div><div className="doctor-list">{filtered.map(d=><article className="doctor-row" key={d.id}><div className="doc-avatar" style={{background:d.color}}>{d.initials}</div><div className="doc-main"><div className="doc-name">{d.name}<span className="verified"><ShieldCheck size={12}/></span></div><div className="doc-meta">{d.specialty}<span>·</span>{d.experience}</div></div><div className="slot-preview"><span>{d.slots.length} openings</span><div className="slot-date">{d.slots.length?niceDate(d.slots[0].day):'No slots'} <span>·</span> {d.slots[0]?.time||''}</div></div><button className="row-arrow" title="View available slots" onClick={()=>setFilter(d.specialty)}><ArrowUpRight size={16}/></button></article>)}{filtered.length===0&&<div className="empty">No doctors match that search.</div>}</div><div className="panel-foot"><span>Availability updates as bookings change</span><span className="live-label"><i/> LIVE</span></div></div>
    <div className="right-col"><div className="panel appointments-panel"><div className="panel-head"><div><div className="section-kicker">LIVE ACTIVITY</div><h2>Appointments</h2></div><span className="count-chip">{appointments.filter(a=>a.status==='booked').length} active</span></div>{appointments.length?<div className="appt-list">{appointments.slice(0,5).map(a=><div className="appt-row" key={a.id}><div className="appt-icon"><CalendarDays size={15}/></div><div className="appt-info"><b>{a.patient_name||'Unnamed patient'}</b><span>{a.doctor} · {niceDate(a.day)} · {a.time}</span><small>{maskPhone(a.patient_phone)} · {a.id}</small></div><span className={'appt-status '+a.status}>{a.status}</span></div>)}</div>:<div className="empty-appt"><div className="empty-symbol"><CalendarDays size={18}/></div><b>No appointments yet</b><span>New bookings will appear here.</span><button onClick={startCall}><Phone size={13}/> Book by voice</button></div>}<div className="appointments-footer"><UsersRound size={14}/> Patients identified by phone number and name</div></div>
     <div className="note-card"><div className="note-icon"><Sparkles size={17}/></div><div><b>Care, made conversational.</b><p>Your assistant can find a time, book a visit, or help cancel an appointment.</p></div><ArrowUpRight size={15}/></div>
    </div></section>
   <footer className="footer"><span>CARELINE <i>·</i> CLINIC OPERATIONS</span><span><span className="privacy"><ShieldCheck size={12}/> Privacy-first by design</span><span className="footer-sep">·</span> Built for better care</span></footer>
  </main>
  {call&&<div className="overlay" onMouseDown={e=>e.target===e.currentTarget&&endCall()}><div className="call-window"><header className="call-head"><div className="call-brand"><span className="call-mark"><HeartPulse size={15}/></span> careline <span className="call-label">VOICE ASSISTANT</span></div><button className="close-call" onClick={endCall}><X size={18}/></button></header><div className="call-body"><div className={'call-orb '+(status==='connected'?'speaking':'')}><div className="orb-inner"><HeartPulse size={28}/></div><span className="orb-ring r1"/><span className="orb-ring r2"/></div><div className="call-state">{status==='connected'?'CONNECTED':status==='connecting'?'CONNECTING':status==='error'?'CONNECTION ISSUE':'CALL ENDED'}</div><h2>Careline Assistant</h2><div className="call-time">{fmt(elapsed)}</div>{status==='connected'&&audioStatus!=='Assistant audio playing'&&<button className="audio-status" onClick={retryAudio}>{audioStatus.startsWith('Audio playback blocked')?'Tap to enable sound':audioStatus}</button>}<div className="call-wave">{Array.from({length:25},(_,i)=><i key={i} style={{'--h':`${8+(Math.sin(i*2.2)+1)*11}px`}}/>)}</div><div className="transcript"><div className="transcript-label">CONVERSATION <span><i/> LIVE</span></div><div className="transcript-lines" ref={transcriptRef}>{messages.map((m,i)=><div className={'message '+m.role} key={i}><div className="message-avatar">{m.role==='assistant'?<HeartPulse size={13}/>:<UserRound size={13}/>}</div><div><small>{m.role==='assistant'?'CARELINE':'YOU'}</small><p>{m.text}</p></div></div>)}</div></div><audio ref={audioRef} autoPlay/></div><div className="call-actions"><button onClick={toggleMute} className={'round-action '+(muted?'is-muted':'')}><span>{muted?<MicOff size={18}/>:<Mic size={18}/>}</span><small>{muted?'Unmute':'Mute'}</small></button><button onClick={endCall} className="end-call"><PhoneOff size={18}/></button><button className="round-action"><span><Volume2 size={18}/></span><small>Speaker</small></button></div><div className="call-safe"><ShieldCheck size={12}/> Your call is private and secure</div></div></div>}
 </div>
}
createRoot(document.getElementById('root')).render(<App/>);
