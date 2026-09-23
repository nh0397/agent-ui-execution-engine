import { useEffect, useRef, useState } from "react";
import { request } from "./api";
export type ChatSnapshot = {
  messages: {role:"you"|"agent";text:string;matches?:string[]|null;run_id?:string}[];
  selected_id:string|null; values:Record<string,string>; initial_request:string; run_id:string|null;
  teaching_mode: "choose" | "discovery" | "recording" | null; return_details: boolean | null;
};
export const emptyChat = (): ChatSnapshot => ({messages:[],selected_id:null,values:{},initial_request:"",run_id:null,teaching_mode:null,return_details:null});
export function useConversationHistory(snapshot:ChatSnapshot, restore:(s:ChatSnapshot)=>void, csrf:string) {
  const [id,setId]=useState("");
  const [ready,setReady]=useState(false);
  const [error,setError]=useState("");
  const [items,setItems]=useState<{id:string;title:string}[]>([]);
  const revision=useRef<Record<string,number>>({});
  const chain=useRef<Promise<unknown>>(Promise.resolve());
  const last=useRef("");
  const restoreRef=useRef(restore);restoreRef.current=restore;
  const blocked=useRef(false);
  async function refresh(){const list=await request<{id:string;title:string}[]>("/conversations");setItems(list);return list;}
  async function load(next:string) {
    setReady(false);
    try {
      await chain.current;
      const value=next ? await request<ChatSnapshot & {revision:number}>(`/conversations/${next}`) : {...emptyChat(),revision:0};
      const data:ChatSnapshot={messages:value.messages,selected_id:value.selected_id,values:value.values,initial_request:value.initial_request,run_id:value.run_id,teaching_mode:value.teaching_mode ?? null,return_details:value.return_details ?? null};
      const nextId=next || crypto.randomUUID();revision.current[nextId]=value.revision;
      last.current=JSON.stringify(data);blocked.current=false;setError("");
      restoreRef.current(data);setId(nextId);setReady(true);
    } catch { setError("Conversation could not be loaded. Reload the page to retry."); }
  }
  useEffect(()=>{
    if(!csrf)return;
    let disposed=false;
    void refresh().then(list=>{if(!disposed) void load(list[0]?.id || "");}).catch(()=>setError("Conversation history is unavailable. Reload to retry."));
    return ()=>{disposed=true;};
  },[csrf]);
  const serialized=JSON.stringify(snapshot);
  useEffect(()=>{
    if(!ready || !id || !snapshot.messages.length || serialized===last.current || blocked.current)return;
    last.current=serialized;
    chain.current=chain.current.then(async()=>{
      if(blocked.current)return;
      try {
        const result=await request<{revision:number}>(`/conversations/${id}`,{method:"PUT",body:JSON.stringify({...JSON.parse(serialized),revision:revision.current[id] || 0})},csrf);
        revision.current[id]=result.revision;await refresh();setError("");
      } catch {blocked.current=true;setError("Changes are not saved. Keep this page open; check the connection and reload the saved conversation before continuing in another window.");}
    });
  },[serialized,ready,id,csrf]);
  return {ready,error,id,items,load};
}
type UsageStatus = { provider:string; model:string; configured:boolean; requests_today:number; daily_request_limit:number; requests_per_minute:number; input_tokens_today:number; output_tokens_today:number; observation:null|{state:string; retry_at?:number; limits?:Record<string,string>} };
export function ModelStatus({csrf}:{csrf:string}) {
  const [value,setValue]=useState<UsageStatus|null>(null);
  const [error,setError]=useState(false);
  useEffect(()=>{
    if(!csrf)return;let disposed=false;
    const poll=()=>request<UsageStatus>("/model/status").then(data=>{if(!disposed){setValue(data);setError(false);}}).catch(()=>{if(!disposed)setError(true);});
    void poll();const timer=setInterval(poll,10000);return()=>{disposed=true;clearInterval(timer);};
  },[csrf]);
  return <details className="model-status"><summary>Model status {value ? `· ${value.provider} · ${value.requests_today}/${value.daily_request_limit} calls${value.requests_today >= value.daily_request_limit * .8 ? " · Limit approaching" : ""}` : ""}</summary>
    {error ? <p>Usage status unavailable.</p> : value ? <>
      <p>{value.model} · {value.configured ? "Configured" : "API key required"}</p>
      <p>App requests today: {value.requests_today} / {value.daily_request_limit}. Resets at 00:00 UTC.</p>
      <p>Maximum {value.requests_per_minute} calls per minute. Reported tokens today: {value.input_tokens_today} input / {value.output_tokens_today} output.</p>
      <p>Last response: {value.observation?.state || "No requests yet"}.</p>
      {value.observation?.retry_at && <p>Retry after {new Date(value.observation.retry_at*1000).toLocaleTimeString()}.</p>}
      {value.observation?.limits ? <p>Provider-reported requests remaining: {value.observation.limits["x-ratelimit-remaining-requests"] ?? "unknown"}. Tokens remaining: {value.observation.limits["x-ratelimit-remaining-tokens"] ?? "unknown"}. These are the last observed limits, shared with other uses of your account.</p> : <p>Provider remaining quota is unknown. The app counter is not your account’s billing total.</p>}
    </> : <p>Loading status…</p>}
  </details>;
}
