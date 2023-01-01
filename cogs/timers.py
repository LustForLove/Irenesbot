from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Embed
from discord.ext import commands, tasks
from numpy.random import randint, seed

from .utils.var import Rid, Cid, Uid, Sid, Ems, Clr

if TYPE_CHECKING:
    from asyncpg import Pool
    from .utils.bot import AluBot


seed(None)


async def get_the_thing(txt_list, name, pool: Pool):
    query = f'UPDATE botinfo SET {name} = {name} + 1 WHERE id=$1 RETURNING {name}'
    val = await pool.fetchval(query, Sid.alu)
    return txt_list[val % len(txt_list)]


async def get_a_text(pool: Pool):
    daily_reminders_txt = [
        f'Hey chat, don\'t forget to spam some emotes in {cmntn(Cid.comfy_spam)} or {cmntn(Cid.emote_spam)}',
        f'Hey chat, if you see some high/elite MMR streamer pick PA/DW - '
        f'don\'t hesitate to ping {umntn(Uid.alu)} about it pretty please !',
        'Hey chat, please use channels according to their description',
        f'Hey chat, please use {rmntn(Rid.bots)} strictly in {cmntn(Cid.bot_spam)} '
        f'(and {rmntn(Rid.nsfwbots)} in {cmntn(Cid.nsfw_bob_spam)}) with exceptions of \n'
        f'0️⃣ feel free to use {umntn(Uid.bot)} everywhere\n'
        f'1️⃣ {umntn(Uid.mango)} in {cmntn(Cid.pubs_talk)}\n'
        f'2️⃣ {umntn(Uid.nqn)}\'s in-built "free-nitro" functions everywhere',
        f'Hey chat, remember to check `$help` and {cmntn(Cid.patch_notes)}. We have a lot of cool features and '
        f'bot commands. Even more to come in future !',
        'Hey chat, follow me on twitch if you haven\'t done it yet: '
        '[twitch.tv/aluerie](https://www.twitch.tv/aluerie) {0} {0} {0}\n'.format(Ems.DankLove),
        f'Hey chat, you can get list of {rmntn(Rid.bots)} available to use in {cmntn(Cid.bot_spam)} and '
        f'{rmntn(Rid.nsfwbots)} in {cmntn(Cid.nsfw_bob_spam)} by respectively checking pins in those channels.'
    ]
    return await get_the_thing(daily_reminders_txt, 'curr_timer', pool)


async def get_important_text(pool: Pool):
    daily_reminders_txt = [
        'Hey chat, check out rules in {0}. Follow them or {1} {1} {1}'.format(cmntn(Cid.rules), Ems.bubuGun),
        f'Hey chat, remember to grab some roles in {cmntn(Cid.roles)} including a custom colour from 140 available !',
        'Hey chat, if you have any suggestions about server/stream/emotes/anything - '
        f'suggest them in {cmntn(Cid.suggestions)} with `$suggest ***` command and discuss them there !',
        'Hey chat, you can set up your birthday date with `$birthday` command for some sweet congratulations '
        f'from us on that day and in {cmntn(Cid.bday_notifs)}.',
        'Hey chat, {0} exist {1} {1} {1}'.format(cmntn(Cid.confessions), Ems.PepoBeliever),
        f'Hey chat, fix your posture {Ems.PepoBeliever}',
        'Hey chat, remember to smile 🙂',
        'Hey chat, feel free to invite new cool people to this server {0} {0} {0}'.format(Ems.peepoComfy),
        'Hey chat, follow étiquette.',
        f'Hey chat, if you ever forget what prefix/help-command bot you want to use have - just look at its nickname, '
        f'for example, {umntn(Uid.nqn)} - means its help command is `++help` and its prefix is `++`',
        'Hey chat, if you ever see {} offline (it should be always at the top of the members list online) - '
        'immediately ping me'.format(umntn(Uid.bot)),
        f'Hey chat, if while watching my stream you see some cool moment - clip it and post to {cmntn(Cid.clips)}',
        'Hey chat, remember to stay hydrated ! {0} {0} {0}'.format(Ems.bubuSip),
        'Hey chat, please react with all kind of hearts on '
        '[this message](https://discord.com/channels/702561315478044804/724996010169991198/866012642627420210)',
        f'Hey chat, if you have any problems then {rmntn(Rid.discord_mods)} can solve it! '
        f'Especially if it is about this server'
    ]
    return await get_the_thing(daily_reminders_txt, 'curr_important_timer', pool)


async def get_fact_text(pool: Pool):
    async def get_msg_count(pool: Pool):
        query = 'SELECT SUM(msg_count) FROM users'
        val = await pool.fetchval(query)
        return val
    daily_reminders_txt = [
        'Hey chat, this server was created on 22/04/2020.',
        'Hey chat, Aluerie made these "interesting daily fact about this server" messages but has no ideas.',
        f'Hey chat, {await get_msg_count(pool)} messages from people in total were sent in this server '
        f'(which my bot tracked)',
        f'Hey chat, <@135119357008150529> was the very first person to join this server - holy poggers '
        f'{Ems.PogChampPepe}'
        # idea to put there the most chatting person who has the most exp and stuff
    ]
    return await get_the_thing(daily_reminders_txt, 'curr_fact_timer', pool)


async def get_gif_text(pool: Pool):
    daily_reminders_txt = [
        'https://media.discordapp.net/attachments/702561315478044807/950421428732325958/peepoSitSlide.gif'
    ]
    return await get_the_thing(daily_reminders_txt, 'curr_gif_timer', pool)


async def get_rule_text(pool: Pool):
    daily_reminders_txt = [
        'Hey chat, follow étiqueté.',
        'Hey chat, remember the rule\n1️⃣ Respect everybody in the server. Be polite.',
        'Hey chat, remember the rule\n2️⃣ Keep the chat in English if possible so everyone understands.',
        'Hey chat, remember the rule\n3️⃣ No racism, sexism or homophobia.',
        'Hey chat, remember the rule\n4️⃣ No offensive language.',
        'Hey chat, remember the rule\n5️⃣ Spam is OK. That means as long as it doesn\'t completely clog chat up '
        'and makes it unreadable then it\'s fine. And well #xxx_spam channels are created to be spammed.',
        'Hey chat, follow étiqueté.',
        'Hey chat, remember the rule\n6️⃣ No spoilers of any kind '
        '(this includes games stories and IRL-things like movies/tournaments/etc). ',
        'Hey chat, remember the rule\n7️⃣ No shady links.',
        'Hey chat, remember the rule\n8️⃣ Be talkative, have fun and enjoy your time! :3',
        'Hey chat, remember the rule\n9️⃣ Nothing that violates discord.gg Terms Of Service '
        '(https://discord.com/terms) & follow their guidelines (https://discord.com/guidelines)',
        'Hey chat, remember the rule\n🔟 Don\'t encourage others to break these rules.'
    ]
    return await get_the_thing(daily_reminders_txt, 'curr_timer', pool)


class Timers(commands.Cog):
    def __init__(self, bot):
        self.bot: AluBot = bot

    async def cog_load(self) -> None:
        self.daily_reminders.start()
        self.daily_important_reminders.start()
        self.daily_fact_reminders.start()
        self.daily_gif_reminders.start()
        self.daily_rule_reminders.start()

    def cog_unload(self) -> None:
        self.daily_reminders.cancel()
        self.daily_important_reminders.cancel()
        self.daily_fact_reminders.cancel()
        self.daily_gif_reminders.cancel()
        self.daily_rule_reminders.cancel()

    async def check_amount_messages(self, msg_amount=10):
        async for msg in self.bot.get_channel(Cid.general).history(limit=msg_amount):
            if msg.author == self.bot.user:
                return True
        return False

    async def timer_work(self, etitle, clr, dscr, rlimit=2, msg_num=10):
        if randint(1, 100 + 1) > rlimit or await self.check_amount_messages(msg_amount=msg_num):
            return
        embed = Embed(title=etitle, color=clr, description=dscr)
        return await self.bot.get_channel(Cid.general).send(embed=embed)

    @tasks.loop(minutes=87)
    async def daily_reminders(self):
        await self.timer_work('Daily Message', Clr.prpl, await get_a_text(self.bot.pool))

    @tasks.loop(minutes=89)
    async def daily_important_reminders(self):
        await self.timer_work('Daily Important Message', Clr.rspbrry, await get_important_text(self.bot.pool))

    @tasks.loop(minutes=157)
    async def daily_fact_reminders(self):
        await self.timer_work('Daily Fact Message', Clr.neon, await get_fact_text(self.bot.pool))

    @tasks.loop(minutes=136)
    async def daily_rule_reminders(self):
        await self.timer_work('Daily Rule Message', 0x66FFBF, await get_rule_text(self.bot.pool))

    @tasks.loop(minutes=97)
    async def daily_gif_reminders(self):
        if randint(1, 100 + 1) > 2 or await self.check_amount_messages():
            return
        await self.bot.get_channel(Cid.general).send(await get_gif_text(self.bot.pool))

    @daily_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @daily_important_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @daily_fact_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @daily_rule_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @daily_gif_reminders.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Timers(bot))
