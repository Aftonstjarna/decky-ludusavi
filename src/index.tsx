import { call, definePlugin } from "@decky/api";
import { PanelSection, PanelSectionRow, ButtonItem } from "@decky/ui";
import { FC, useEffect, useState } from "react";
import { LuDatabaseBackup } from "react-icons/lu";
import { registerDependencies } from "./util/registrations";
const Content: FC = () => {
  const [status, setStatus] = useState("Connecting to backend…");
  const refresh = () => call<[], { enabled: boolean; queued: number; scanCount: number }>("savehaven_status")
    .then(s => setStatus(`${s.enabled ? "Hooks enabled" : "Paused"} · ${s.queued} jobs · ${s.scanCount} scans this session`))
    .catch(() => setStatus("Backend unavailable. Check the plugin logs or whether port 8765 is already in use."));
  useEffect(() => { refresh(); }, []);
  return <PanelSection title="Savehaven · sandbox">
    <PanelSectionRow>Uses game start/exit events. No periodic save scans.</PanelSectionRow>
    <PanelSectionRow>{status}</PanelSectionRow>
    <PanelSectionRow>Web interface: http://127.0.0.1:8765</PanelSectionRow>
    <PanelSectionRow>Map Steam App IDs and edit backup preferences in the web interface. Only SaveDemo files are managed in this build.</PanelSectionRow>
    <ButtonItem onClick={refresh}>Refresh status</ButtonItem>
  </PanelSection>;
};
export default definePlugin(() => {
  const unregisterDependencies = registerDependencies();
  return { name: "Savehaven Ludusavi", content: <Content />, icon: <LuDatabaseBackup />, onDismount: unregisterDependencies };
});
