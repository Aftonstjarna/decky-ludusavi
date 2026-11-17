import asyncio
import os
import subprocess
import json
try:
    import decky  # type: ignore
except ImportError:
    from savehaven_runtime import decky


class Ludusavi:
    bin_path: list[str] = None
    version: str

    _env: dict[str, str]

    def __init__(self, bin_paths: list[str], config_dir: str | None = None):
        self.bin_path = None
        self._active_pids = set()
        self.config_dir = config_dir
        self._set_env()

        for path in bin_paths:
            if self._try_initialize(*(path if isinstance(path, list) else __import__("shlex").split(path))):
                break

        decky.logger.info("Using Binary: %s", self.bin_path)

    async def preview_saves(self):
        return await self._run_command(["backup", "--preview", "--no-cloud-sync"])

    async def backup_game_async(self, game_name: str):
        return await self._run_command(
            ["backup", "--force", game_name],
            "backup_game_complete",
        )

    async def restore_game_async(
        self,
        game_name: str,
        backup_id: str,
        preview: bool = False,
        api_mode: bool = True,
    ):
        cmd = ["restore", "--backup", backup_id, game_name]
        if preview:
            cmd.append("--preview")
        else:
            cmd.append("--force")

        return await self._run_command(
            cmd,
            "restore_game_complete",
            api_mode=api_mode,
        )

    async def sync_game_cloud_state_async(
        self,
        game_name: str,
        direction: str = "download",
        preview: bool = False,
        api_mode: bool = True,
    ):
        if not (direction == "upload" or direction == "download"):
            raise ValueError("Invalid direction. Use 'upload' or 'download'.")

        cmd = ["cloud", direction, game_name]
        if preview:
            cmd.append("--preview")
        else:
            cmd.append("--force")

        return await self._run_command(
            cmd,
            "sync_game_cloud_state_complete",
            api_mode=api_mode,
        )

    async def get_game_backups(self, game_name: str):
        return await self._run_command(
            ["backups", game_name],
        )

    async def get_config(self):
        return await self._run_command(
            ["config", "show"],
        )
    
    async def get_normalized_game_name(self, game_name: str):
        return await self._run_command(
            ["find", "--normalized", game_name],
            api_mode=False,
        )

    async def get_game_name_by_app_id(self, app_id: str):
        return await self._run_command(
            ["find", "--steam-id", app_id],
        )

    async def update_manifest_async(self):
        return await self._run_command(
            ["manifest", "update", "--force"],
            "update_manifest_complete",
            api_mode=False,
        )

    async def _run_command(
        self, cmd: list[str], event: str | None = None, api_mode: bool = True
    ):
        if not self.bin_path:
            raise Exception("Ludusavi binary not found")

        cmd = [*self.bin_path, *(["--config", self.config_dir, "--no-manifest-update"] if self.config_dir else []), *cmd]
        if api_mode:
            cmd.append("--api")

        decky.logger.info("Running command: %s", subprocess.list2cmdline(cmd))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                env=self._env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._active_pids.add(process.pid)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=getattr(self, "timeout", 45))
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise RuntimeError("Ludusavi timed out")
            finally:
                self._active_pids.discard(process.pid)
            if process.returncode:
                raise RuntimeError(f"Ludusavi exited {process.returncode}: {stderr.decode(errors='replace')[-1000:]}")

            result_str = stdout.decode()
            decky.logger.debug(result_str)

            if api_mode:
                result_str = json.loads(result_str)

            if event:
                await decky.emit(event, result_str)

            return result_str

        except Exception as e:
            if event:
                await decky.emit(event, {"errors": {"pluginError": str(e)}})

            raise

    def _set_env(self):
        # Fix env for flatpak support.
        self._env = os.environ.copy()

        if "XDG_RUNTIME_DIR" not in self._env:
            self._env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
        if "LD_LIBRARY_PATH" in self._env:
            del self._env["LD_LIBRARY_PATH"]

        decky.logger.debug("Prepared Ludusavi process environment")

    def _try_initialize(self, *bin_path: str) -> bool:
        try:
            decky.logger.debug("Trying binary: %s", bin_path)
            output = subprocess.check_output(
                [*bin_path, "--version"],
                env=self._env,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
            )

            decky.logger.debug("Command Output: %s", output)

            self.bin_path = bin_path
            self.version = output

            return True
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            decky.logger.error(e)
        except subprocess.CalledProcessError as e:
            decky.logger.error(e)
            decky.logger.error(e.output)
            return False

    async def install(self):
        process = await asyncio.create_subprocess_exec(
            *[
                "flatpak",
                "install",
                "--or-update",
                "-u",
                "-y",
                "--app",
                "com.github.mtkennerly.ludusavi",
                "--noninteractive",
            ],
            env=self._env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        decky.logger.info("Ludusavi Update Result: %s", stdout.decode())

        if process.returncode != 0:
            await decky.emit(
                "install_ludusavi_complete",
                {"errors": {"pluginError": "Failed to install Ludusavi."}},
            )
            return

        self.__init__(["flatpak run com.github.mtkennerly.ludusavi"])
        await decky.emit("install_ludusavi_complete", {"result": "ok"})
