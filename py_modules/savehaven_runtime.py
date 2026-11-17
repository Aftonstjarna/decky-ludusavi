"""Minimal event/log adapter when the upstream backend runs outside Decky."""
import logging
class Runtime:
    logger = logging.getLogger("savehaven.ludusavi")
    async def emit(self, event, result):
        self.logger.debug("Completed event %s", event)
decky = Runtime()
