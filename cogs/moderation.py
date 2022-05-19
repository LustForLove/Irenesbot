from __future__ import annotations
from typing import TYPE_CHECKING

from discord import Embed, Forbidden, Member, app_commands
from discord.ext import commands, tasks
from discord.utils import format_dt, sleep_until

from utils.var import *
from utils import database as db
from utils.time import DTFromStr, arg_to_timetext
from utils.context import Context

import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import func

if TYPE_CHECKING:
    from discord import Message
    from discord import Interaction

blocked_phrases = ['https://cdn.discordapp.com/emojis/831229578340859964.gif?v=1']


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.help_category = 'Mute'

    @commands.Cog.listener()
    async def on_message(self, msg: Message):
        if any(i in msg.content for i in blocked_phrases):
            embed = Embed(colour=Clr.prpl)
            content = '{0} not allowed {1} {1} {1}'.format(msg.author.mention, Ems.peepoPolice)
            embed.description = 'Blocked phase. A warning for now !'
            await msg.channel.send(content=content, embed=embed)
            await msg.delete()

    @commands.has_role(Rid.discord_mods)
    @app_commands.default_permissions(manage_messages=True)
    @commands.hybrid_command(
        name='warn',
        brief=Ems.slash,
        description='Warn member'
    )
    @app_commands.describe(member='Member to warn', reason='Reason')
    async def warn(self, ctx, member: Member, *, reason="No reason"):
        """Give member a warning"""
        if member.id == Uid.irene:
            return await ctx.reply(f"You can't do that to Irene {Ems.bubuGun}")
        if member.bot:
            return await ctx.reply("Don't bully bots, please")
        db.append_row(
            db.w, key='warn', name='manual', dtime=ctx.message.created_at, userid=member.id, modid=ctx.author.id,
            reason=reason
        )
        em = Embed(colour=Clr.prpl, title="Manual warning by a mod", description=reason)
        em.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        em.set_footer(text=f"Warned by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        await ctx.reply(embed=em)

    @commands.has_role(Rid.discord_mods)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(member='Member to ban', reason='Reason')
    @commands.hybrid_command(
        name='ban',
        brief=Ems.slash,
        description='Ban member from the server'
    )
    async def ban(self, ctx, member: Member, *, reason: str = "No reason"):
        """Ban member from the server"""
        em = Embed(colour=Clr.red, title="Ban member")
        em.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        em.add_field(name='Reason', value=reason)
        await member.ban(reason=reason)
        await ctx.reply(embed=em)

    async def mute_work(self, ctx, member, duration: timedelta, reason):
        try:
            await member.timeout(duration, reason=reason)
        except Forbidden:
            em = Embed(color=Clr.error, description=f'You can not mute that member')
            em.set_author(name='MissingPermissions')
            return await ctx.reply(embed=em, ephemeral=True)

        em = Embed(color=Clr.prpl, title="Mute member", description=f'mute for {duration}')
        em.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        em.add_field(name='Reason', value=reason)
        content = member.mention if ctx.interaction else ''
        await ctx.reply(content=content, embed=em)

    @app_commands.default_permissions(manage_messages=True)
    @app_commands.command(
        name='mute',
        description="Mute+timeout member from chatting"
    )
    @app_commands.describe(member='Member to mute+timeout', duration='Duration of the mute', reason='Reason')
    async def mute_slh(self, ctx: Interaction, member: Member, duration: str, *, reason: str = "No reason"):
        duration = DTFromStr(duration)
        ctx = await Context.from_interaction(ctx)
        await self.mute_work(ctx, member, duration.delta, reason)

    @commands.has_role(Rid.discord_mods)
    @commands.command(
        name='mute',
        brief=Ems.slash,
        usage='<time> [reason]'
    )
    async def mute_ext(self, ctx: Context, member: Member, *, duration_reason: str = "5 min No reason"):
        """Mute+timeout member from chatting"""
        duration, reason = arg_to_timetext(duration_reason)
        await self.mute_work(ctx, member, timedelta(seconds=duration), reason)

    @commands.has_role(Rid.discord_mods)
    @app_commands.default_permissions(manage_messages=True)
    @commands.hybrid_command(
        name='unmute',
        brief=Ems.slash,
        description='Remove timeout+mute from member'
    )
    @app_commands.describe(member='Member to unmute', reason='Reason')
    async def unmute(self, ctx, member: Member, *, reason: str = 'No reason'):
        """Remove timeout+mute from member"""
        await member.timeout(None, reason=reason)
        em = Embed(color=Clr.prpl, title="Unmute member")
        em.description = f"{member.mention}, you are unmuted now, congrats {Ems.bubuSip}"
        em.add_field(name='Reason', value=reason)
        em.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        content = member.mention if ctx.interaction else ''
        await ctx.reply(content=content, embed=em)

    @commands.Cog.listener()
    async def on_member_update(self, before: Member, after: Member):
        if before.is_timed_out() == after.is_timed_out() or after.guild.id != Sid.irene:  # member is not muted/unmuted
            return

        if before.is_timed_out() is False and after.is_timed_out() is True:  # member is muted
            em = Embed(colour=Clr.red)
            em.set_author(
                name=f'{after.display_name} is muted until',
                icon_url=after.display_avatar.url
            )
            em.description = format_dt(after.timed_out_until, style="R")
            await self.bot.get_channel(Cid.logs).send(embed=em)

        elif before.is_timed_out() is True and after.is_timed_out() is False:  # member is unmuted
            return  # apparently discord limitation > it doesnt ever happen


class PlebModeration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.help_category = 'Tools'
        self.active_mutes = {}
        self.check_mutes.start()

    @commands.hybrid_command(
        name='selfmute',
        brief=Ems.slash,
        description='Mute yourself for chosen duration'
    )
    @app_commands.describe(duration='Choose duration of the mute')
    async def selfmute(self, ctx: Context, *, duration: str = '5 minutes'):
        duration = DTFromStr(duration)
        if not timedelta(minutes=5) <= duration.delta <= timedelta(days=1):
            em = Embed(colour=Clr.red).set_author(name='BadTimeArgument')
            em.description = 'Sorry! Duration of selfmute should satisfy `10 minutes < duration < 24 hours`'
            return await ctx.reply(embed=em)
        selfmute_rl = ctx.guild.get_role(Rid.selfmuted)

        if ctx.author._roles.has(Rid.selfmuted):
            return await ctx.send(f'Somehow you are already muted {Ems.DankFix}')

        warning = f'Are you sure you want to be muted until this time: {duration.fdt_r}?' \
                  f'\n**Do not ask the moderators to undo this!**'
        confirm = await ctx.prompt(warning)
        if not confirm:
            return await ctx.send('Aborting...', delete_after=5.0)

        await ctx.author.add_roles(selfmute_rl)

        em2 = Embed(colour=Clr.red).set_author(name=f'{ctx.author.display_name} is selfmuted until')
        em2.description = duration.fdt_r
        await ctx.guild.get_channel(Cid.logs).send(embed=em2)

        old_max_id = int(db.session.query(func.max(db.u.id)).scalar() or 0)
        db.add_row(
            db.u,
            1 + old_max_id,
            userid=ctx.author.id,
            channelid=ctx.channel.id,
            dtime=duration.dt,
            reason='Selfmute'
        )
        em = Embed(colour=ctx.author.colour)
        em.description = f'Muted until this time: {duration.fdt_r}. Be sure not to bother anyone about it.'
        await ctx.send(embed=em)
        if duration.dt < self.check_mutes.next_iteration.replace(tzinfo=timezone.utc):
            self.bot.loop.create_task(self.fire_the_unmute(1 + old_max_id, ctx.author.id, duration.dt))

    @tasks.loop(minutes=30)
    async def check_mutes(self):
        for row in db.session.query(db.u):
            if row.dtime.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc) + timedelta(minutes=30):
                if row.id in self.active_mutes:
                    continue
                self.active_mutes[row.id] = row
                self.bot.loop.create_task(self.fire_the_unmute(row.id, row.userid, row.dtime))

    async def fire_the_unmute(self, id_, userid, dtime):
        dtime = dtime.replace(tzinfo=timezone.utc)
        await sleep_until(dtime)
        irene_server = self.bot.get_guild(Sid.irene)
        selfmute_rl = irene_server.get_role(Rid.selfmuted)
        member = irene_server.get_member(userid)
        await member.remove_roles(selfmute_rl)
        db.remove_row(db.u, id_)
        self.active_mutes.pop(id_, None)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        selfmute_rl = channel.guild.get_role(Rid.selfmuted)
        muted_rl = channel.guild.get_role(Rid.muted)
        await channel.set_permissions(selfmute_rl, view_channel=False)
        await channel.set_permissions(muted_rl, send_messages=False)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
    await bot.add_cog(PlebModeration(bot))
