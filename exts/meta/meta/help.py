from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

import discord
from discord import app_commands
from discord.ext import commands, menus

from utils import AluCog, AluContext, ExtCategory, aluloop, const, pagination
from utils.formats import human_timedelta

from .._category import MetaCog

if TYPE_CHECKING:
    from utils import AluBot


class CogPage:
    def __init__(
        self,
        cog: Literal['_front_page'] | AluCog | commands.Cog,  # dirty way to handle front page
        cmds: Sequence[commands.Command],
        category: ExtCategory,
        page_num: int = 0,
        page_len: int = 0,
        category_page: int = 0,
        category_len: int = 1,
    ):
        self.cog: Literal['_front_page'] | AluCog | commands.Cog = cog
        self.cmds: Sequence[commands.Command] = cmds
        self.page_num: int = page_num  # page per cog so mostly 0
        self.page_len: int = page_len
        self.category_page: int = category_page
        self.category_len: int = category_len
        self.category: ExtCategory = category


class HelpPageSource(menus.ListPageSource):
    def __init__(self, data: Dict[ExtCategory, List[CogPage]]):
        entries = list(itertools.chain.from_iterable(data.values()))
        super().__init__(entries=entries, per_page=1)

    async def format_page(self, menu: HelpPages, page: CogPage):
        e = discord.Embed(colour=const.Colour.prpl())
        e.set_footer(text=f'With love, {menu.help_cmd.context.bot.user.display_name}')

        if page.cog == '_front_page':
            bot = menu.ctx_ntr.client
            owner = bot.owner
            e.title = f'{bot.user.name}\'s Help Menu'
            e.description = (
                f'{bot.user.name} is an ultimate multi-purpose bot !\n\n'
                'Use dropdown menu below to select a category.'
            )
            e.add_field(name=f'{owner.name}\'s server', value='[Link](https://discord.gg/K8FuDeP)')
            e.add_field(name='GitHub', value='[Link](https://github.com/Aluerie/AluBot)')
            e.add_field(name='Bot Owner', value=f'@{owner}')
            e.set_thumbnail(url=bot.user.display_avatar)
            e.set_author(name=f'Made by {owner.display_name}', icon_url=owner.display_avatar)
            return e

        emote = getattr(page.cog, 'emote', None)
        triple_emote = '{0} {0} {0}'.format(emote) if emote else ''
        e.title = f'{page.cog.qualified_name} {triple_emote} (Section page {page.page_num + 1}/{page.page_len})'
        emote_url = discord.PartialEmoji.from_str(page.category.emote)
        author_text = f'Category: {page.category.name} (Category page {page.category_page + 1}/{page.category_len})'
        e.set_author(name=author_text, icon_url=emote_url.url)
        e.description = page.cog.description
        for c in page.cmds:
            e.add_field(
                name=menu.help_cmd.get_command_signature(c),
                value=menu.help_cmd.get_command_value(c),
                inline=False,
            )
        return e


class HelpSelect(discord.ui.Select):
    def __init__(self, paginator: HelpPages):
        super().__init__(placeholder='Choose help category')
        self.paginator: HelpPages = paginator

        self.__fill_options()

    def __fill_options(self) -> None:
        pages_per_category: Mapping[ExtCategory, Tuple[int, int]] = {}
        total = 1
        for category, cog_pages in self.paginator.help_data.items():
            starting = total
            total += len(cog_pages)
            pages_per_category[category] = starting, total - 1

        for category, (start, end) in pages_per_category.items():
            pages_string = f'(page {start})' if start == end else f'(pages {start}-{end})'
            self.add_option(
                label=f'{category.name} {pages_string}',
                emoji=category.emote,
                description=category.description,
                value=str(start - 1),  # we added 1 in total=1
            )

    async def callback(self, ntr: discord.Interaction[AluBot]):
        page_to_open = int(self.values[0])
        await self.paginator.show_page(ntr, page_to_open)


class HelpPages(pagination.Paginator):
    source: HelpPageSource

    def __init__(
        self,
        ctx: AluContext | discord.Interaction[AluBot],
        help_cmd: AluHelp,
        help_data: Dict[ExtCategory, List[CogPage]],
    ):
        self.help_cmd: AluHelp = help_cmd
        self.help_data: Dict[ExtCategory, List[CogPage]] = help_data
        super().__init__(ctx, HelpPageSource(help_data))

        self.add_item(HelpSelect(self))


class AluHelp(commands.HelpCommand):
    context: AluContext

    # todo: idk
    def __init__(self, show_hidden: bool = False) -> None:
        super().__init__(
            show_hidden=show_hidden,
            verify_checks=False,  # TODO: idk we need to decide this
            command_attrs={
                'hidden': False,
                'help': 'Show `help` menu for the bot.',
                'usage': '[command/section]',
            },
        )

    async def unpack_commands(
        self, command: commands.Command, answer: Optional[list[commands.Command]] = None, deep: int = 0
    ) -> List[commands.Command]:
        """If a command is a group then unpack those until their very-last children.

        examples:
        /help -> [/help]
        /tag (create delete owner etc) -> [/tag create, /tag delete, /tag delete, /tag etc]
        same for 3depth children.
        """
        if answer is None:
            answer = []  # so the array only exists inside the command.
        if getattr(command, 'commands', None) is not None:  # maybe we should isinstance(commands.Group)
            for x in await self.filter_commands(command.commands):  # , sort=True): # type: ignore
                await self.unpack_commands(x, answer=answer, deep=deep + 1)
        else:
            answer.append(command)
        return answer

    def get_command_signature(self, command: commands.Command) -> str:
        def signature():
            sign = f' `{command.signature}`' if command.signature else ''
            name = command.name if not getattr(command, 'root_parent') else command.root_parent.name  # type:ignore
            app_command = self.context.bot.tree.get_app_command(name)
            if app_command:
                cmd_mention = f"</{command.qualified_name}:{app_command.id}>"
            else:
                prefix = getattr(self.context, 'clean_prefix', '$')
                cmd_mention = f'`{prefix}{command.qualified_name}`'
            return f'{cmd_mention}{sign}'

        def aliases():
            if len(command.aliases):
                return ' | aliases: ' + '; '.join([f'`{ali}`' for ali in command.aliases])
            return ''

        def cd():
            if command.cooldown is not None:
                return f' | cd: {command.cooldown.rate} per {human_timedelta(command.cooldown.per, strip=True, suffix=False)}'
            return ''

        def check():
            if command.checks:
                res = set(getattr(i, '__doc__') or "mods only" for i in command.checks)
                res = [f"*{i}*" for i in res]
                return f"**!** {', '.join(res)}\n"
            return ''

        return f'\N{BLACK CIRCLE} {signature()}{aliases()}{cd()}\n{check()}'

    def get_command_value(self, command: commands.Command) -> str:
        # help string
        help_str = command.help or 'No documentation'
        split = help_str.split('\n', 1)
        extra_info = ' [...]' if len(split) > 1 else ''
        help_str = help_str + extra_info
        return help_str

    def get_bot_mapping(self) -> Dict[ExtCategory, Dict[AluCog | commands.Cog, List[commands.Command]]]:
        """Retrieves the bot mapping passed to :meth:`send_bot_help`."""

        # TODO: include solo slash commands and Context Menu commands.
        categories = self.context.bot.category_cogs

        mapping = {category: {cog: cog.get_commands() for cog in cog_list} for category, cog_list in categories.items()}
        # todo: think how to sort front page to front
        return mapping

    async def send_bot_help(
        self,
        mapping: Dict[ExtCategory, Dict[AluCog | commands.Cog, List[commands.Command]]],
    ):
        await self.context.typing()

        help_data: Dict[ExtCategory, List[CogPage]] = {}

        for category, cog_cmd_dict in mapping.items():
            for cog, cmds in cog_cmd_dict.items():
                filtered = await self.filter_commands(cmds)  # , sort=True)
                if filtered:
                    cmds_strings = list(
                        itertools.chain.from_iterable([await self.unpack_commands(c) for c in filtered])
                    )
                    cmds10 = [cmds_strings[i : i + 10] for i in range(0, len(cmds_strings), 10)]
                    page_len = len(cmds10)
                    for counter, page_cmds in enumerate(cmds10):
                        page = CogPage(
                            cog=cog,
                            cmds=page_cmds,
                            page_num=counter,
                            page_len=page_len,
                            category=category,
                        )
                        help_data.setdefault(category, []).append(page)

        for category, cog_pages in help_data.items():
            cog_len = len(cog_pages)
            for counter, page in enumerate(cog_pages):
                page.category_len = cog_len
                page.category_page = counter

        help_data = dict(sorted(help_data.items(), key=lambda x: (int(x[0].sort_back), x[0].name)))

        index_category = ExtCategory(name='Index page', emote='\N{SWAN}', description='Index page')
        index_pages = [CogPage(cog='_front_page', cmds=[], page_num=0, category=index_category)]

        help_data = {index_category: index_pages} | help_data
        pages = HelpPages(self.context, self, help_data)
        await pages.start()


class AluHelpCog(MetaCog):
    """Help command."""

    def __init__(self, bot: AluBot, *args, **kwargs):
        super().__init__(bot, *args, **kwargs)
        bot.help_command = AluHelp()
        bot.help_command.cog = self
        self._original_help_command: Optional[commands.HelpCommand] = bot.help_command

    async def cog_load(self) -> None:
        self.load_help_info.start()

    async def cog_unload(self) -> None:
        self.load_help_info.cancel()
        self.bot.help_command = self._original_help_command

    @app_commands.command(name='help')
    @app_commands.describe(command='Command name to get help about.')
    async def slash_help(self, ntr: discord.Interaction, *, command: Optional[str]):
        """Show help menu for the bot."""
        # todo: starting category
        my_help = AluHelp()
        my_help.context = ctx = await AluContext.from_interaction(ntr)
        await my_help.command_callback(ctx, command=command)

    @commands.is_owner()
    @commands.command(hidden=True)
    async def devhelp(self, ctx: AluContext, *, command: Optional[str]):
        my_help = AluHelp(show_hidden=True)
        my_help.context = ctx
        await my_help.command_callback(ctx, command=command)

    @aluloop(count=1)
    async def load_help_info(self):
        # auto-syncing is bad, but is auto-fetching commands bad to fill the cache?
        # If I ever get rate-limited here then we will think :thinking:
        await self.bot.tree.fetch_commands()

        if not self.bot.test:
            # announce to community/hideout that we logged in
            # from testing purposes it means we can use help with [proper slash mentions (if synced).
            e = discord.Embed(colour=const.Colour.prpl())
            e.description = f'Logged in as {self.bot.user.name}'
            await self.hideout.spam.send(embed=e)
            e.set_footer(text='Finished updating/rebooting')
            await self.community.bot_spam.send(embed=e)


async def setup(bot: AluBot):
    await bot.add_cog(AluHelpCog(bot))
