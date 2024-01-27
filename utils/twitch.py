from __future__ import annotations

import datetime
import logging
import re
from typing import TYPE_CHECKING, Optional, TypedDict, override

import discord
import twitchio
from discord.ext.commands import BadArgument
from twitchio.ext import eventsub

import config

from . import const, formats

if TYPE_CHECKING:
    from bot import AluBot


log = logging.getLogger(__name__)


class TwitchClient(twitchio.Client):
    def __init__(self, bot: AluBot):
        super().__init__(token=config.TWITCH_ACCESS_TOKEN)

        self._bot: AluBot = bot
        self.eventsub: eventsub.EventSubWSClient = eventsub.EventSubWSClient(self)

    # EVENT SUB

    async def event_eventsub_notification(self, event: eventsub.NotificationEvent) -> None:
        if isinstance(event.data, eventsub.StreamOnlineData):
            self._bot.dispatch("twitchio_stream_start", event.data)

        # testing with channel points
        elif isinstance(event.data, eventsub.CustomRewardRedemptionAddUpdateData):
            self._bot.dispatch("twitchio_channel_points_redeem", event.data)

    # OVERRIDE

    @override
    async def event_error(self, error: Exception, data: Optional[str] = None):
        embed = discord.Embed(colour=const.Colour.twitch(), title="Twitch Client Error")
        if data:
            embed.description = data[2048:]
        await self._bot.exc_manager.register_error(error, source=embed, where="Twitch Client")

    # UTILITIES

    async def fetch_streamer(self, twitch_id: int) -> Streamer:
        user = next(iter(await self.fetch_users(ids=[twitch_id])))
        stream = next(iter(await self.fetch_streams(user_ids=[twitch_id])), None)  # None if offline
        return Streamer(self, user, stream)


class Streamer:
    """My own helping class that unites twitchio.User and twitch.Stream together
    Do not confuse "streamer" with "user" or "stream" terms. It's meant to be a concatenation.

    The problem is neither classes have full information.

    Attributes
    ----------
    twitch_id
        Twitch ID
    name

    """

    if TYPE_CHECKING:
        live: bool
        game: str
        title: str
        preview_url: str

    def __init__(self, _twitch: TwitchClient, user: twitchio.User, stream: twitchio.Stream | None):
        self._twitch: TwitchClient = _twitch

        self.id: int = user.id
        self.display_name: str = user.display_name
        self.avatar_url: str = user.profile_image
        self.url: str = f"https://www.twitch.tv/{user.name}"

        if stream:
            self.live = True
            self.game = stream.game_name
            self.title = stream.title
            self.preview_url = stream.thumbnail_url.replace("{width}", "640").replace("{height}", "360")
        else:
            self.live = False
            self.game = "Offline"
            self.title = "Offline"
            if offline_image := user.offline_image:
                self.preview_url = f'{"-".join(offline_image.split("-")[:-1])}-640x360.{offline_image.split(".")[-1]}'
            else:
                self.preview_url = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{user.name}-640x360.jpg"

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.display_name} id={self.id} title={self.title}>"

    async def vod_link(self, *, seconds_ago: int = 0, markdown: bool = True) -> str:
        """Get latest vod link, timestamped to timedelta ago"""
        video = next(iter(await self._twitch.fetch_videos(user_id=self.id, period="day")), None)
        if not video:
            return ""

        duration = formats.hms_to_seconds(video.duration)
        new_hms = formats.divmod_timedelta(duration - seconds_ago)
        url = f"{video.url}?t={new_hms}"
        return f"/[VOD]({url})" if markdown else url

    async def game_art_url(self) -> str | None:
        if self.live:
            game = next(iter(await self._twitch.fetch_games(names=[self.game])), None)
            if game:
                return game.art_url(285, 380)
            else:
                return None
        else:
            return None
