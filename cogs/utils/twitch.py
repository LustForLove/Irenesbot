from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from discord.ext.commands import BadArgument

from twitchio import Client

from cogs.utils.format import gettimefromhms, display_hmstime

if TYPE_CHECKING:
    from asyncpg import Pool
    from twitchio import User, Video, Stream

log = logging.getLogger(__name__)



class TwitchClient(Client):
    def __init__(self, token: str):
        super().__init__(token)

    async def twitch_id_by_name(self, user_name: str) -> int:
        """Gets twitch_id by user_login"""
        try:
            user: User = (await self.fetch_users(names=[user_name]))[0]
            return user.id
        except IndexError:
            raise BadArgument(f'Error checking stream `{user_name}`.\n User either does not exist or is banned.')

    async def name_by_twitch_id(self, user_id: int) -> str:
        """Gets display_name by twitch_id"""
        try:
            user: User = (await self.fetch_users(ids=[user_id]))[0]
            return user.display_name
        except IndexError:
            raise BadArgument(f'Error checking stream `{user_id}`.\n User either does not exist or is banned.')

    async def twitch_id_and_display_name_by_login(self, user_login: str) -> (int, str):
        """Gets tuple (twitch_id, display_name) by user_login from one call to twitch client"""
        try:
            user: User = (await self.fetch_users(names=[user_login]))[0]
            return user.id, user.display_name
        except IndexError:
            raise BadArgument(f'Error checking stream `{user_login}`.\n User either does not exist or is banned.')

    async def last_vod_link(self, user_id: int, epoch_time_ago: int = 0, md: bool = True) -> str:
        """Get last vod link for user with `user_id` with timestamp as well"""
        try:
            video: Video = (await self.fetch_videos(user_id=user_id, period='day'))[0]  # type: ignore
            duration = gettimefromhms(video.duration)
            vod_url = f'{video.url}?t={display_hmstime(duration - epoch_time_ago)}'
            return f'/[TwVOD]({vod_url})' if md else vod_url
        except IndexError:
            return ''

    async def get_live_lol_player_ids(self, pool: Pool) -> List[int]:
        """Get twitch ids for live League of Legends streams"""
        query = f"""SELECT twitch_id, id
                    FROM lol_players
                    WHERE id=ANY(
                        SELECT DISTINCT(unnest(lolfeed_stream_ids)) FROM guilds
                    )
                """
        twitch_id_to_fav_id_dict = {r.twitch_id: r.id for r in await pool.fetch(query)}

        live_twitch_ids = [
            i.user.id
            for i in await self.fetch_streams(user_ids=list(twitch_id_to_fav_id_dict.keys()))
        ]
        return [twitch_id_to_fav_id_dict[i] for i in live_twitch_ids]

    async def get_twitch_stream(self, twitch_id: int) -> TwitchStream:
        user = (await self.fetch_users(ids=[twitch_id]))[0]
        stream = (await self.fetch_streams(user_ids=[twitch_id]))[0]
        return TwitchStream(twitch_id, user, stream)


class TwitchStream:

    __slots__ = (
        'twitch_id',
        'display_name',
        'name',
        'game',
        'url',
        'logo_url',
        'online',
        'title',
        'preview_url'
    )

    if TYPE_CHECKING:
        display_name: str
        name: str
        game: str
        url: str
        logo_url: str
        online: bool
        title: str
        preview_url: str

    def __init__(self, twitch_id: int, user: User, stream: Stream):
        self.twitch_id = twitch_id
        self._update(user, stream)

    def __repr__(self):
        return f"<Stream id={self.twitch_id} name={self.name} online={self.online} title={self.title}>"

    def _update(self, user: User, stream: Stream):
        self.display_name = user.display_name
        self.name = user.name
        self.url = f'https://www.twitch.tv/{self.display_name}'
        self.logo_url = user.profile_image

        if stream:
            self.online = True
            self.game = stream.game_name
            self.title = stream.title
            self.preview_url = stream.thumbnail_url.replace('{width}', '640').replace('{height}', '360')
        else:
            self.online = False
            self.game = 'Offline'
            self.title = 'Offline'
            if n := user.offline_image:
                self.preview_url = f'{"-".join(n.split("-")[:-1])}-640x360.{n.split(".")[-1]}'
            else:
                self.preview_url = f'https://static-cdn.jtvnw.net/previews-ttv/live_user_{self.name}-640x360.jpg'


async def main():
    from config import TWITCH_TOKEN
    tc = TwitchClient(token=TWITCH_TOKEN)
    await tc.connect()
    gorgc_id = await tc.twitch_id_by_name('gorgc')
    v = await tc.get_twitch_stream(gorgc_id)
    print(v)
    await tc.close()


if __name__ == '__main__':
    import asyncio
    logging.basicConfig()
    log.setLevel(logging.DEBUG)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
    # loop.close()
