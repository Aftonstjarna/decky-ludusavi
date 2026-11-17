// Savehaven adaptation: keep Decky's lifecycle events, queue work in Python.
import { call } from "@decky/api";
import { log } from "./backend";
declare const appStore: any;
async function sendLifecycle(appId: number, event: "start" | "exit") {
  let name = "";
  try { name = appStore.GetAppOverviewByAppID(appId)?.display_name ?? ""; } catch {}
  try {
    await call("savehaven_event", String(appId), event, name);
  } catch (error) {
    console.error("Savehaven lifecycle event failed", error);
    await log(`Savehaven ${event} hook failed for ${appId}: ${String(error)}`, "error").catch(() => {});
  }
}
export const onGameStart = (appId: number) => sendLifecycle(appId, "start");
export const onGameExit = (appId: number) => sendLifecycle(appId, "exit");
// Retained for the upstream manual UI components, which are not mounted by Savehaven.
export { backup as backupGame } from "./backend";
