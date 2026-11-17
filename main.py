import asyncio
import config
import decky  # type: ignore
from ludusavi import Ludusavi
import logging
from pathlib import Path
from savehaven_service import Service
from live_backend import LiveService

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
        value = config.game_config.getSetting(key)
        if value is None and hasattr(self.service.automation, 'submit'):
            value = {'name': key, 'alias': key, 'autoSync': key not in self.service.automation.settings['excluded']}
        return value

    async def set_game_config(self, key: str, value):
        decky.logger.debug("Executing: set_game_config('%s', '%s')", key, value)
        config.game_config.setSetting(key, value)
        backend = self.service.automation
        if hasattr(backend, 'submit'):
            with backend.lock:
                excluded = set(backend.settings['excluded'])
                if value.get('autoSync'): excluded.discard(key)
                else: excluded.add(key)
                backend.settings['excluded'] = sorted(excluded)
                backend.settings.setdefault('gameAliases', {})[key] = value.get('alias', key)
                backend.persist()

    async def backup_game(self, game_name: str):
        decky.logger.debug("Executing: backup_game('%s')", game_name)
        if hasattr(self.service.automation, 'submit'):
            asyncio.create_task(self._live_event({'action':'backup','games':[game_name]}, 'backup_game_complete'))
        else:
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
        if hasattr(self.service.automation, 'submit'):
            asyncio.create_task(self._live_event({'action':'restore-preview' if preview else 'restore','games':[game_name],'backup':backup_id}, 'restore_game_complete', api_mode))
            return
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

    async def _live_event(self, data, event, api_mode=True):
        import json
        try:
            result = await asyncio.to_thread(self.service.automation.execute, data)
            await decky.emit(event, result if api_mode else json.dumps(result, indent=2))
        except Exception as exc:
            await decky.emit(event, {'errors': {'pluginError': str(exc)}})

    async def get_game_backups(self, game_name: str):
        decky.logger.debug("Executing: get_game_backups('%s')", game_name)
        if hasattr(self.service.automation, 'submit'):
            return await asyncio.to_thread(self.service.automation.execute, {'action':'backups','games':[game_name]})
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
        return await asyncio.to_thread(self.service.automation.hook, {"appId": app_id, "event": event, "name": name})

    async def savehaven_action(self, data: dict):
        backend = self.service.automation
        return await asyncio.to_thread(backend.submit if hasattr(backend, 'submit') else backend.action, data)

    async def savehaven_live(self, data: dict):
        return await asyncio.to_thread(self.service.automation.submit, data)

    async def savehaven_files(self):
        return await asyncio.to_thread(self.service.sandbox.listing)

    async def savehaven_file_action(self, data: dict):
        result = await asyncio.to_thread(self.service.sandbox.action, data)
        if data.get('action') in ('save', 'restore') and self.service.automation.settings['enabled']:
            self.service.automation.enqueue([data['id']], 'web-file-edit')
        return result

    async def savehaven_status(self):
        return await asyncio.to_thread(self.service.automation.status)

    async def _main(self):
        root = Path(decky.DECKY_USER_HOME) / "SaveDemo"
        web = Path(decky.DECKY_PLUGIN_DIR) / "web"
        marker = Path(decky.DECKY_USER_HOME) / 'Saves' / '.savehaven.json'
        import json
        live = marker.is_file() and json.loads(marker.read_text()).get('kind') == 'savehaven-live'
        if live:
            self.service = await asyncio.to_thread(LiveService, Path(decky.DECKY_USER_HOME), web, 8765)
        else:
            self.service = await asyncio.to_thread(Service, root, web, 8765)
        self.ludusavi = self.service.automation.adapter
        self.service.start()
        decky.logger.info("Savehaven hooks ready; web UI at http://127.0.0.1:8765 ")

    async def _unload(self):
        if hasattr(self, "service"):
            await asyncio.to_thread(self.service.close)

    # Migrations that should be performed before entering `_main()`.
    async def _migration(self):
        config.migrate()
