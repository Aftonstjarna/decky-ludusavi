import { call, definePlugin } from "@decky/api";
import { PanelSection, PanelSectionRow, ButtonItem, Dropdown, DialogButton, Focusable, ToggleField, ConfirmModal, showModal } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { LuDatabaseBackup } from "react-icons/lu";
import { FaDownload, FaUpload } from "react-icons/fa";
import { LivePanel } from "./LivePanel";
import { registerDependencies } from "./util/registrations";
type Entry = { id: string; name: string; platform: string; decision: string; reason: string; override: string; appId: string };
type Status = { live?: boolean; enabled: boolean; queued: number; scanCount: number; version: string; entries: Entry[] };
type Save = { id: string; revision: string; backups: string[] };
const Restore: FC<{game: Entry; closeModal?: () => void}> = ({game, closeModal}) => {
  const [save,setSave]=useState<Save>();
  const [version,setVersion]=useState<string>();
  const [preview,setPreview]=useState<{current:string;backup:string}>();
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{call<[],{files:Save[]}>("savehaven_files").then(r=>{const f=r.files.find(f=>f.id===game.id);setSave(f);setVersion(f?.backups[0]);if(!f?.backups.length)setError("No restorable sandbox snapshots. Restore mode in the web interface lists supported saves.");}).catch(e=>setError(String(e)));},[game.id]);
  useEffect(()=>{let active=true;setPreview(undefined);if(save&&version)call<[object],{current:string;backup:string}>("savehaven_file_action",{action:"preview",id:game.id,revision:save.revision,backup:version}).then(p=>{if(active){setPreview(p);setError("");}}).catch(e=>{if(active)setError(String(e));});return()=>{active=false;};},[save,version]);
  return <ConfirmModal strTitle={`Restore: ${game.name}`} strOKButtonText="Restore" bOKDisabled={!preview||busy} closeModal={closeModal} onCancel={closeModal} onOK={async()=>{setBusy(true);try{await call("savehaven_file_action",{action:"restore",id:game.id,revision:save!.revision,backup:version});closeModal?.();}catch(e){setError(String(e));}finally{setBusy(false);}}}>
    <p>The current save will be backed up before restoring.</p>
    {!!save?.backups.length&&<Dropdown rgOptions={save.backups.map(b=>({label:b,data:b}))} selectedOption={version} onChange={v=>setVersion(v.data)} />}
    {error&&<p>{error}</p>}{preview&&<div style={{maxHeight:"16em",overflow:"auto",whiteSpace:"pre-wrap",wordBreak:"break-word"}}><h4>Current save</h4>{preview.current}<h4>Selected backup</h4>{preview.backup}</div>}
  </ConfirmModal>;
};
const Content: FC = () => {
  const [status,setStatus]=useState<Status>();
  const [selected,setSelected]=useState<string>();
  const [message,setMessage]=useState("Connecting to backend…");
  const [busy,setBusy]=useState(false);
  const refresh=async()=>{try{const s=await call<[],Status>("savehaven_status");setStatus(s);setSelected(id=>id||s.entries?.[0]?.id);setMessage(`${s.queued} queued · ${s.scanCount} scans this session`);}catch(e){setMessage(String(e));}};
  useEffect(()=>{refresh();},[]);
  const action=async(data:object)=>{setBusy(true);try{const s=await call<[object],Status>("savehaven_action",data);setStatus(s);setMessage(`${s.queued} queued · ${s.scanCount} scans this session`);}catch(e){setMessage(String(e));}finally{setBusy(false);}};
  const game=status?.entries?.find(e=>e.id===selected);
  if (status?.live) return <LivePanel />;
  return <>
    <PanelSection><PanelSectionRow><Dropdown rgOptions={(status?.entries||[]).map(e=>({label:e.name,data:e.id}))} selectedOption={selected} onChange={e=>setSelected(e.data)} /></PanelSectionRow>
      {game&&<PanelSectionRow><Focusable flow-children="horizontal" style={{display:"flex",gap:"0.5em"}}>
        <DialogButton style={{minWidth:0}} disabled={busy||game.decision!=="Included"} onClick={()=>action({action:"scan",ids:[game.id]})}><FaUpload /> Backup</DialogButton>
        <DialogButton style={{minWidth:0}} disabled={busy} onClick={()=>showModal(<Restore game={game} />)}><FaDownload /> Restore</DialogButton>
      </Focusable></PanelSectionRow>}
    </PanelSection>
    {game&&<PanelSection title="Game Config">
      <PanelSectionRow><Dropdown rgOptions={[{label:"Automatic (exclude working Steam Cloud)",data:"auto"},{label:"Always include this copy",data:"include"},{label:"Always exclude this copy",data:"exclude"}]} selectedOption={game.override} onChange={e=>action({action:"rule",id:game.id,override:e.data})} disabled={busy} /></PanelSectionRow>
      <PanelSectionRow>{game.platform} · {game.decision}<br/>{game.reason}</PanelSectionRow>
      <PanelSectionRow>{game.appId?`Steam App ID: ${game.appId}`:"Map this game's Steam App ID in the web interface to enable its exit hook."}</PanelSectionRow>
    </PanelSection>}
    <PanelSection title="Global Config"><PanelSectionRow><ToggleField label="Sync after closing game" description="Use game events; no periodic save scans." checked={status?.enabled||false} disabled={busy||!status} onChange={enabled=>action({action:"enabled",enabled})} /></PanelSectionRow></PanelSection>
    <PanelSection title="Ludusavi"><PanelSectionRow>{status?.version||"Loading version…"}</PanelSectionRow><PanelSectionRow>{message}</PanelSectionRow><ButtonItem disabled={busy} onClick={refresh}>Refresh status</ButtonItem><PanelSectionRow>Web interface: http://127.0.0.1:8765<br/>SaveDemo sandbox</PanelSectionRow></PanelSection>
  </>;
};
export default definePlugin(() => {
  const unregisterDependencies = registerDependencies();
  return { name: "Savehaven Ludusavi", content: <Content />, icon: <LuDatabaseBackup />, onDismount: unregisterDependencies };
});
