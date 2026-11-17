import { call } from '@decky/api';
import { ButtonItem, PanelSection, PanelSectionRow, ToggleField } from '@decky/ui';
import { FC, useEffect, useState } from 'react';
import appState from './util/state';
import { GameConfigurationPanel } from './components/sidebar/GameConfigurationPanel';
export const LivePanel: FC = () => {
 const [s,setS]=useState<any>();const [message,setMessage]=useState('Loading Ludusavi…');
 const refresh=()=>call<[],any>('savehaven_status').then(v=>{setS(v);if(!appState.currentState.recent_games.length){const names=Object.keys(v.preview?.games||{}).slice(0,5);appState.setState('recent_games',names);appState.setState('recent_games_selected',names[0]);}setMessage(v.error||`${v.queued} queued · ${v.scanCount} scans`);}).catch(e=>setMessage(String(e)));
 useEffect(()=>{appState.initialize().then(refresh);},[]);
 const action=(data:object)=>call<[object],any>('savehaven_live',data).then(v=>{setS(v);setMessage('Settings saved');}).catch(e=>setMessage(String(e)));
 return <><GameConfigurationPanel/><PanelSection title="Global Config"><PanelSectionRow><ToggleField label="Back up on game exit" checked={s?.enabled||false} onChange={enabled=>action({action:'settings',enabled})}/></PanelSectionRow><PanelSectionRow><ToggleField label="Centralize save folders" description="After Ludusavi backup, link save-only folders into ~/Saves." checked={s?.centralize||false} onChange={centralize=>action({action:'settings',centralize})}/></PanelSectionRow></PanelSection><PanelSection title="Ludusavi"><PanelSectionRow>{s?.version}</PanelSectionRow><PanelSectionRow>{message}</PanelSectionRow><ButtonItem onClick={refresh}>Refresh status</ButtonItem><PanelSectionRow>Web interface: http://127.0.0.1:8765<br/>Syncthing: {s?.syncthing?.configured?s.syncthing.label:'Not configured'}</PanelSectionRow></PanelSection></>;
};
