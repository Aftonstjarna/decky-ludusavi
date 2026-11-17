import asyncio
import config
import decky  # type: ignore
from ludusavi import Ludusavi
import logging
from pathlib import Path
from savehaven_service import Service

decky.logger.setLevel("INFO")


class Plugin:
    ludusavi: Ludusavi

    # Check plugin for initialization
    async def get_ludusavi_version(self):
        decky.logger.debug("Executing: get_ludusavi_version()")
        return {"bin_path": self.ludusavi.bin_path, "version": self.ludusavi.version}

    async def install_ludusavi(self):
        decky.logger.debug("Executing: install_ludusavi()")
        asyncio.create_task(self.ludusavi.install())

    async def get_config(self, key: str):
        decky.logger.debug("Executing: get_config('%s')", key)
        return config.app_config.getSetting(key)

    async def set_config(self, key: str, value):
        decky.logger.debug("Executing: set_config('%s', '%s')", key, value)
        return config.app_config.setSetting(key, value)

    async def get_game_config(self, key: str):
        decky.logger.debug("Executing: get_game_config('%s')", key)
        return config.game_config.getSetting(key)

    async def set_game_config(self, key: str, value):
        decky.logger.debug("Executing: set_game_config('%s', '%s')", key, value)
        config.game_config.setSetting(key, value)

    async def backup_game(self, game_name: str):
        decky.logger.debug("Executing: backup_game('%s')", game_name)
        asyncio.create_task(self.ludusavi.backup_game_async(game_name))

    async def get_normalized_game_name(self, game_name: str):
        decky.logger.debug("Executing: get_normalized_game_name('%s')", game_name)
        return await self.ludusavi.get_normalized_game_name(game_name)

    async def restore_game(
        self, game_name: str, backup_id: str, preview: bool, api_mode: bool
    ):
        decky.logger.debug(
            "Executing: restore_game('%s', '%s', %b, %b)",
            game_name,
            backup_id,
            preview,
            api_mode,
        )
        asyncio.create_task(
            self.ludusavi.restore_game_async(game_name, backup_id, preview, api_mode)
        )

    async def sync_game_cloud_state(
        self, game_name: str, direction: str, preview: bool, api_mode: bool
    ):
        decky.logger.debug(
            "Executing: sync_game_cloud_state('%s', '%s', %b, %b)",
            game_name,
            direction,
            preview,
            api_mode,
        )
        asyncio.create_task(
            self.ludusavi.sync_game_cloud_state_async(
                game_name, direction, preview, api_mode
            )
        )

    async def get_game_backups(self, game_name: str):
        decky.logger.debug("Executing: get_game_backups('%s')", game_name)
        return await self.ludusavi.get_game_backups(game_name)

    async def get_plugin_logs(self):
        with open(decky.DECKY_PLUGIN_LOG) as f:
            return f.read()

    async def get_ludusavi_config(self):
        decky.logger.debug("Executing: get_ludusavi_config()")
        return await self.ludusavi.get_config()

    async def get_game_name_by_appid_from_manifest(self, app_id: str):
        decky.logger.debug("Executing: get_game_name_by_appid_from_manifest('%s')", app_id)
        return await self.ludusavi.get_game_name_by_app_id(app_id)

    async def update_manifest(self): 
        decky.logger.info("Executing: update_manifest()")
        asyncio.create_task(self.ludusavi.update_manifest_async())

    async def log(self, message: str, level: str = "info"):
        level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warn": logging.WARN,
            "error": logging.ERROR,
            "critical": logging.CRITICAL
        }
        decky.logger.log(level_map.get(level.lower(), logging.INFO), message)

    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded
    async def savehaven_event(self, app_id: str, event: str, name: str = ""):
        return self.service.automation.hook({"appId": app_id, "event": event, "name": name})

    async def savehaven_status(self):
        return await asyncio.to_thread(self.service.automation.status)

    async def _main(self):
        root = Path(decky.DECKY_USER_HOME) / "SaveDemo"
        web = Path(decky.DECKY_PLUGIN_DIR) / "web"
        self.service = await asyncio.to_thread(Service, root, web, 8765)
        self.ludusavi = self.service.automation.adapter
        self.service.start()
        decky.logger.info("Savehaven hooks ready; web UI at http://127.0.0.1:8765 (sandbox)")

    async def _unload(self):
        if hasattr(self, "service"):
            await asyncio.to_thread(self.service.close)

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        config.migrate()
