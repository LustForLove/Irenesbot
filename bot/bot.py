from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import os
import sys
import textwrap
from typing import TYPE_CHECKING, Any, Literal, override

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import MISSING

import config
from bot import EXT_CATEGORY_NONE, AluContext, ExtCategory
from ext import get_extensions
from utils import cache, const, disambiguator, errors, formats, helpers, transposer
from utils.dota.steamio import Dota2Client
from utils.twitch import AluTwitchClient

from .exc_manager import ExceptionManager
from .intents_perms import INTENTS, PERMISSIONS
from .timer import TimerManager
from .tree import AluAppCommandTree

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, MutableMapping, Sequence

    import asyncpg
    from aiohttp import ClientSession
    from discord.abc import Snowflake

    from bot import AluCog
    from utils.database import DotRecord, PoolTypedWithAny


__all__ = ("AluBot",)

log = logging.getLogger(__name__)


class AluBotHelper(TimerManager):
    """Extra class to help with MRO."""

    def __init__(self, *, bot: AluBot) -> None:
        super().__init__(bot=bot)


class AluBot(commands.Bot, AluBotHelper):
    """AluBot."""

    if TYPE_CHECKING:
        user: discord.ClientUser
        #     bot_app_info: discord.AppInfo
        #     launch_time: datetime.datetime
        logs_via_webhook_handler: Any
        #     prefixes: PrefixConfig
        tree: AluAppCommandTree
        #     cogs: Mapping[str, AluCog]
        old_tree_error: Callable[
            [discord.Interaction[AluBot], discord.app_commands.AppCommandError],
            Coroutine[Any, Any, None],
        ]
        command_prefix: set[Literal["~", "$"]]  # default is some mix of Iterable[str] and Callable
        listener_connection: asyncpg.Connection[asyncpg.Record]

    def __init__(
        self,
        test: bool = False,
        *,
        session: ClientSession,
        pool: asyncpg.Pool[asyncpg.Record],
        **kwargs: Any,
    ) -> None:
        """Initialize the AluBot.

        Parameters
        ----------
        session : ClientSession
            aiohttp.ClientSession to use within the bot.
        pool : asyncpg.Pool[DotRecord]
            A connection pool to the database.
        test : bool, optional
            whether the bot is a testing version (YenBot) or main production bot (AluBot), by default False
        kwargs : Any
            kwargs for the purpose of MRO and what not.

        """
        self.test: bool = test
        self.main_prefix: Literal["~", "$"] = "~" if test else "$"

        super().__init__(
            command_prefix={self.main_prefix},
            activity=discord.Streaming(
                name="\N{PURPLE HEART} /help /setup",
                url="https://www.twitch.tv/irene_adler__",
            ),
            intents=INTENTS,
            allowed_mentions=discord.AllowedMentions(roles=True, replied_user=False, everyone=False),  # .none()
            tree_cls=AluAppCommandTree,
            strip_after_prefix=True,
            case_insensitive=True,
        )
        self.database: asyncpg.Pool[asyncpg.Record] = pool
        self.pool: PoolTypedWithAny = pool  # type: ignore # asyncpg typehinting crutch, read `utils.database` for more
        self.session: ClientSession = session

        self.exc_manager: ExceptionManager = ExceptionManager(self)
        self.transposer: transposer.TransposeClient = transposer.TransposeClient(session=session)
        self.disambiguator: disambiguator.Disambiguator = disambiguator.Disambiguator()

        self.repo_url: str = "https://github.com/Aluerie/AluBot"
        self.developer: str = "Aluerie"  # it's my GitHub account name
        self.server_url: str = "https://discord.gg/K8FuDeP"

        self.category_cogs: dict[ExtCategory, list[AluCog]] = {}

        self.mimic_message_user_mapping: MutableMapping[int, int] = cache.ExpiringCache(
            seconds=datetime.timedelta(days=7).seconds
        )

        self.prefix_cache: dict[int, set[str]] = {}

        self.twitch = AluTwitchClient(self)
        self.dota = Dota2Client(self)

    @override
    async def setup_hook(self) -> None:
        self.bot_app_info: discord.AppInfo = await self.application_info()

        os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"
        os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
        os.environ["JISHAKU_HIDE"] = "True"  # need to be before loading jsk

        failed_to_load_all_exts = False
        for ext in get_extensions(self.test):
            try:
                await self.load_extension(ext)
            except Exception as error:
                failed_to_load_all_exts = True
                embed = discord.Embed(
                    colour=0xDA9F93,
                    description=f"Failed to load extension `{ext}`.",
                ).set_footer(text=f'setup_hook: loading extension "{ext}"')
                await self.exc_manager.register_error(error, embed)

        await self.populate_database_cache()
        await self.create_database_listeners()

        # we could go with attribute option like exceptions manager
        # but let's keep its methods nearby in AluBot namespace
        # needs to be done after cogs are loaded so all cog event listeners are ready
        super(AluBotHelper, self).__init__(bot=self)

        if self.test:

            async def try_auto_sync_with_logging() -> None:
                try:
                    result = await self.try_hideout_auto_sync()
                except Exception as err:
                    log.error("Autosync: failed %s.", const.Tick.No, exc_info=err)
                else:
                    if result:
                        log.info("Autosync: success %s.", const.Tick.Yes)
                    else:
                        log.info("Autosync: not needed %s.", const.Tick.Black)

            if not failed_to_load_all_exts:
                self.loop.create_task(try_auto_sync_with_logging())
            else:
                log.info(
                    "Autosync: cancelled %s One or more cogs failed to load.",
                    const.Tick.No,
                )

    async def try_hideout_auto_sync(self) -> bool:
        """Try auto copy-global+sync for hideout guild."""
        # Inspired by:
        # licensed MPL v2 from DuckBot-Discord/DuckBot `try_autosync`
        # https://github.com/DuckBot-Discord/DuckBot/blob/rewrite/bot.py

        # tag ass, and all. But strictly for convenient development purposes.
        # let's try min-maxing auto-sync in my hideout/debug guild in my test bot.

        # safeguard. Need the app id.
        await self.wait_until_ready()

        guild = discord.Object(id=self.hideout.id)
        self.tree.copy_global_to(guild=guild)

        all_cmds = self.tree.get_commands(guild=guild)

        new_payloads = [(guild.id, cmd.to_dict(self.tree)) for cmd in all_cmds]

        query = "SELECT payload FROM auto_sync WHERE guild_id = $1"
        db_payloads = [r["payload"] for r in await self.pool.fetch(query, guild.id)]

        updated_payloads = [p for _, p in new_payloads if p not in db_payloads]
        outdated_payloads = [p for p in db_payloads if p not in [p for _, p in new_payloads]]
        not_synced = updated_payloads + outdated_payloads

        if not_synced:
            await self.pool.execute("DELETE FROM auto_sync WHERE guild_id = $1", guild.id)
            await self.pool.executemany(
                "INSERT INTO auto_sync (guild_id, payload) VALUES ($1, $2)",
                new_payloads,
            )

            await self.tree.sync(guild=guild)
            return True
        else:
            return False

    async def populate_database_cache(self) -> None:
        """Populate cache coming from the database."""
        prefix_data: list[tuple[int, set[str]]] = await self.pool.fetch("SELECT guild_id, prefixes FROM guilds")
        self.prefix_cache = {guild_id: prefixes for guild_id, prefixes in prefix_data if prefixes}

    @override
    async def get_prefix(self, message: discord.Message) -> list[str]:
        """Return the prefixes for the given message.

        Parameters
        ----------
        message
            The message to get the prefix of.

        """
        cached_prefixes = self.prefix_cache.get((message.guild and message.guild.id or 0), None)
        base_prefixes = set(cached_prefixes) if cached_prefixes else self.command_prefix
        return commands.when_mentioned_or(*base_prefixes)(self, message)

    async def create_database_listeners(self) -> None:
        """Register listeners for database events."""
        self.listener_connection = await self.pool.acquire()  # type: ignore

        async def _delete_prefixes_event(
            conn: asyncpg.Connection[DotRecord], pid: int, channel: str, payload: str
        ) -> None:
            from_json = discord.utils._from_json(payload)
            with contextlib.suppress(Exception):
                del self.prefix_cache[from_json["guild_id"]]

        async def _create_or_update_event(
            conn: asyncpg.Connection[DotRecord], pid: int, channel: str, payload: str
        ) -> None:
            from_json = discord.utils._from_json(payload)
            self.prefix_cache[from_json["guild_id"]] = set(from_json["prefixes"])

        # they want `conn` in functions above to be type-hinted as
        # `asyncpg.Connection[Any] | asyncpg.pool.PoolConnectionProxy[Any]`
        # and payload as `object`
        # while we define those params very clearly in .sql and here.
        await self.listener_connection.add_listener("delete_prefixes", _delete_prefixes_event)  # type: ignore
        await self.listener_connection.add_listener("update_prefixes", _create_or_update_event)  # type: ignore

    @override
    async def add_cog(
        self,
        cog: AluCog,
        /,
        *,
        override: bool = False,
        guild: Snowflake | None = MISSING,
        guilds: Sequence[Snowflake] = MISSING,
    ) -> None:
        await super().add_cog(cog, override=override, guild=guild, guilds=guilds)

        # jishaku does not have a category thus we have this weird typehint
        category = getattr(cog, "category", None)
        if not category or not isinstance(category, ExtCategory):
            category = EXT_CATEGORY_NONE

        self.category_cogs.setdefault(category, []).append(cog)

    async def on_ready(self) -> None:
        """Handle `ready` event."""
        if not hasattr(self, "launch_time"):
            self.launch_time = datetime.datetime.now(datetime.UTC)
        # if hasattr(self, "dota"):
        #     await self.dota.wait_until_ready()
        log.info("Logged in as `%s`", self.user)

    @override
    async def start(self) -> None:
        # erm, bcs of my horrendous .test logic we need to do it in a weird way
        # todo: is there anything better ? :D

        # if not self.test or "ext.fpc.dota" in get_extensions(self.test):

        #
        #     await asyncio.gather(
        #         super().start(config.DISCORD_BOT_TOKEN, reconnect=True),
        #         self.dota.login(),
        #     )
        # else:

        # await super().start(config.DISCORD_BOT_TOKEN, reconnect=True)
        await asyncio.gather(
            super().start(config.DISCORD_BOT_TOKEN, reconnect=True),  # VALVE_SWITCH
            self.twitch.start(),
            self.dota.login(),
        )

    @override
    async def get_context(self, origin: discord.Interaction | discord.Message) -> AluContext:
        return await super().get_context(origin, cls=AluContext)

    @property
    def owner(self) -> discord.User:
        """Get bot's owner user."""
        return self.bot_app_info.owner

    # instantiate INITIALIZE EXTRA ATTRIBUTES/CLIENTS/FUNCTIONS

    # The following functions are `initialize_something`
    # which import some heavy modules and initialize some ~heavy clients under bot namespace
    # they should be used in `__init__` or in `cog_load` methods in cog classes that need to work with them,
    # i.e. fpc dota notifications should call
    # `bot.initialize_dota`, `bot.initialize_dota_cache`, `bot.initialize_twitch`, etc.
    # This is done exclusively so when I run only a few cogs on test bot
    # I don't need to load those heavy modules/clients.
    #
    # note that I import inside the functions which is against pep8 but apparently it is not so bad:
    # pep8 answer: https://stackoverflow.com/a/1188672/19217368
    # points to import inside the function: https://stackoverflow.com/a/1188693/19217368
    # and I exactly want these^

    # async def initialize_dota_pulsefire_clients(self) -> None:
    #     """Initialize Dota 2 pulsefire-like clients.

    #     * OpenDota API pulsefire client
    #     * Stratz API pulsefire client
    #     """
    #     if not hasattr(self, "opendota"):
    #         from utils.dota import ODotaConstantsClient, OpenDotaClient, SteamWebAPIClient, StratzClient

    #         self.opendota = OpenDotaClient()
    #         await self.opendota.__aenter__()

    #         self.stratz = StratzClient()
    #         await self.stratz.__aenter__()

    #         self.odota_constants = ODotaConstantsClient()
    #         await self.odota_constants.__aenter__()

    #         self.steam_web_api = SteamWebAPIClient()
    #         await self.steam_web_api.__aenter__()

    def instantiate_lol(self) -> None:
        """Instantiate League of Legends Client."""
        if not hasattr(self, "lol"):
            from utils.lol.lol_client import LeagueClient

            self.lol = LeagueClient(self)

    async def instantiate_dota(self) -> None:
        """Initialize Dota 2 Client.

        * Dota 2 Client, allows communicating with Dota 2 Game Coordinator and Steam
        """
        if not hasattr(self, "dota"):
            from utils.dota.steamio import Dota2Client

            self.dota = Dota2Client(self)  # VALVE_SWITCH
            # await self.dota.login()

    # def instantiate_dota(self) -> None:
    #     """Instantiate Dota 2 Client.

    #     * Dota 2 Client, allows communicating with Dota 2 Game Coordinator and Steam
    #     """
    #     if not hasattr(self, "dota"):
    #         from utils.dota.valvepython import DotaClient

    #         self.dota = DotaClient(self)

    def initialize_github(self) -> None:
        """Initialize GitHub REST API Client."""
        if not hasattr(self, "github"):
            from githubkit import GitHub

            self.github = GitHub(config.GIT_PERSONAL_TOKEN)

    async def initialize_twitch(self) -> None:
        """Initialize subclassed twitchio's Twitch Client."""
        if not hasattr(self, "twitch"):
            from utils.twitch import AluTwitchClient

            self.twitch = AluTwitchClient(self)
            await self.twitch.login()

    def initialize_tz_manager(self) -> None:
        """Initialize TimeZone Manager."""
        if not hasattr(self, "tz_manager"):
            from utils.timezones import TimezoneManager

            self.tz_manager = TimezoneManager(self)

    @override
    async def close(self) -> None:
        """Close the connection to Discord while cleaning up other open sessions and clients."""
        await self.pool.close()

        if hasattr(self, "twitch"):
            await self.twitch.close()
        if hasattr(self, "dota"):
            await self.dota.close()
        if hasattr(self, "lol"):
            await self.lol.close()

        await super().close()
        # session needs to be closed the last probably
        if hasattr(self, "session"):
            await self.session.close()

    @property
    def hideout(self) -> const.HideoutGuild:
        """Shortcut to get Hideout guild, its channels and roles."""
        return const.HideoutGuild(self)

    @property
    def community(self) -> const.CommunityGuild:
        """Shortcut to get Community guild, its channels and roles."""
        return const.CommunityGuild(self)

    @discord.utils.cached_property
    def invite_link(self) -> str:
        """Get invite link for the bot."""
        return discord.utils.oauth_url(
            self.user.id,
            permissions=PERMISSIONS,
            scopes=("bot", "applications.commands"),
        )

    def webhook_from_url(self, url: str) -> discord.Webhook:
        """A shortcut function with filled in discord.Webhook.from_url args."""
        return discord.Webhook.from_url(
            url=url,
            session=self.session,
            client=self,
            bot_token=self.http.token,
        )

    async def webhook_from_database(self, channel_id: int) -> discord.Webhook:
        query = "SELECT url FROM webhooks WHERE channel_id = $1"
        webhook_url: str | None = await self.pool.fetchval(query, channel_id)
        if webhook_url:
            return self.webhook_from_url(webhook_url)
        else:
            msg = f"There is no webhook in the database for channel with id={channel_id}"
            raise errors.PlaceholderRaiseError(msg)

    @discord.utils.cached_property
    def spam_webhook(self) -> discord.Webhook:
        """A shortcut to spam webhook."""
        return self.webhook_from_url(config.SPAM_WEBHOOK)

    @discord.utils.cached_property
    def error_webhook(self) -> discord.Webhook:
        """A shortcut to error webhook."""
        return self.webhook_from_url(config.ERROR_WEBHOOK)

    @property
    def error_ping(self) -> str:
        """Error Role ping used to notify Irene about some errors."""
        return config.ERROR_PING

    @override
    async def on_error(self: AluBot, event: str, *args: Any, **kwargs: Any) -> None:
        """Called when an error is raised in an event listener.

        Parameters
        ----------
        event: str
            The name of the event that raised the exception.
        args: Any
            The positional arguments for the event that raised the exception.
        kwargs: Any
            The keyword arguments for the event that raised the exception.

        """
        # Exception Traceback
        (_exception_type, exception, _traceback) = sys.exc_info()
        if exception is None:
            exception = TypeError("Somehow `on_error` fired with exception being `None`.")

        # Silence command errors that somehow get bubbled up far enough here
        # if isinstance(exception, commands.CommandInvokeError):
        #     return

        # ridiculous attempt to eliminate 404 that appear for Hybrid commands for my own usage.
        # that I can't really remove via on_command_error since they appear before we can do something about it.
        # maybe we need some rewrite about it tho; like ignore all discord.HTTPException
        if (
            isinstance(args[0], AluContext)
            and args[0].author.id == const.User.aluerie
            and isinstance(exception, discord.NotFound)
        ):
            return

        embed = (
            discord.Embed(
                colour=0xA32952,
                title=f"`{event}`",
            )
            .set_author(name="Event Error")
            .add_field(
                name="Args",
                value=(
                    "```py\n" + "\n".join(f"[{index}]: {arg!r}" for index, arg in enumerate(args)) + "```"
                    if args
                    else "No Args"
                ),
                inline=False,
            )
            .set_footer(text=f"AluBot.on_error: {event}")
        )
        await self.exc_manager.register_error(exception, embed)

    @override
    async def on_command_error(self, ctx: AluContext, error: commands.CommandError | Exception) -> None:
        """Handler called when an error is raised while invoking a ctx command.

        In case of problems - check out on_command_error in parent BotBase class - it's not simply `pass`
        """
        if ctx.is_error_handled is True:
            return

        # error handler working variables
        desc = "No description"
        is_unexpected = False
        mention = True

        # error handler itself.

        match error:
            # CHAINED ERRORS
            case commands.HybridCommandError() | commands.CommandInvokeError() | app_commands.CommandInvokeError():
                # we aren't interested in the chain traceback.
                return await self.on_command_error(ctx, error.original)

            # MY OWN ERRORS
            case errors.AluBotError():
                # These errors are generally raised in code by myself or by my code with an explanation text as `error`
                # AluBotError subclassed exceptions are all mine.
                desc = f"{error}"

            # UserInputError SUBCLASSED ERRORS
            case commands.BadLiteralArgument():
                desc = (
                    f"Sorry! Incorrect argument value: {error.argument!r}. \n"
                    f"Only these options are valid for a parameter `{error.param.displayed_name or error.param.name}`:\n"
                    f"{formats.human_join([repr(l) for l in error.literals])}."
                )

            case commands.EmojiNotFound():
                desc = f"Sorry! `{error.argument}` is not a custom emote."
            case commands.BadArgument():
                desc = f"{error}"

            case commands.MissingRequiredArgument():
                desc = f"Please, provide this argument:\n`{error.param.name}`"
            case commands.CommandNotFound():
                if ctx.prefix in ["/", f"<@{ctx.bot.user.id}> ", f"<@!{ctx.bot.user.id}> "]:
                    return
                if ctx.prefix == "$" and ctx.message.content[1].isdigit():
                    # "$200 for this?" 2 is `ctx.message.content[1]`
                    # prefix commands should not start with digits
                    return
                # TODO: make a fuzzy search in here to recommend the command that user wants
                desc = f"Please, double-check, did you make a typo? Or use `{ctx.prefix}help`"
            case commands.CommandOnCooldown():
                desc = f"Please retry in `{formats.human_timedelta(error.retry_after, mode='brief')}`"
            case commands.NotOwner():
                desc = f"Sorry, only {ctx.bot.owner} as the bot developer is allowed to use this command."
            case commands.MissingRole():
                desc = f"Sorry, only {error.missing_role} are able to use this command."
            case commands.CheckFailure():
                desc = f"{error}"

            # elif isinstance(error, errors.SilentError):
            #     # this will fail the interaction hmm
            #     return
            case _:
                # error is unhandled/unclear and thus developers need to be notified about it.
                is_unexpected = True

                cmd_name = f"{ctx.clean_prefix}{ctx.command.qualified_name if ctx.command else 'non-cmd'}"
                metadata_embed = (
                    discord.Embed(
                        colour=0x890620,
                        title=f"Error with `{ctx.clean_prefix}{ctx.command}`",
                        url=ctx.message.jump_url,
                        description=textwrap.shorten(ctx.message.content, width=1024),
                        # timestamp=ctx.message.created_at,
                    )
                    .set_author(
                        name=f"@{ctx.author} in #{ctx.channel} ({ctx.guild.name if ctx.guild else "DM Channel"})",
                        icon_url=ctx.author.display_avatar,
                    )
                    .add_field(
                        name="Command Args",
                        value=(
                            "```py\n" + "\n".join(f"[{name}]: {value!r}" for name, value in ctx.kwargs.items()) + "```"
                            if ctx.kwargs
                            else "```py\nNo arguments```"
                        ),
                        inline=False,
                    )
                    .add_field(
                        name="Snowflake Ids",
                        value=(
                            "```py\n"
                            f"author  = {ctx.author.id}\n"
                            f"channel = {ctx.channel.id}\n"
                            f"guild   = {ctx.guild.id if ctx.guild else "DM Channel"}```"
                        ),
                    )
                    .set_footer(
                        text=f"on_command_error: {cmd_name}",
                        icon_url=ctx.guild.icon if ctx.guild else ctx.author.display_avatar,
                    )
                )
                mention = bool(ctx.channel.id != ctx.bot.hideout.spam_channel_id)
                await ctx.bot.exc_manager.register_error(error, metadata_embed, mention=mention)

        response_embed = helpers.error_handler_response_embed(error, is_unexpected, desc, mention)
        await ctx.reply(embed=response_embed, ephemeral=True)
