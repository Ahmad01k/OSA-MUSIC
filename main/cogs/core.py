import datetime as dt
import traceback
import discord
import humanize
import wavelink
from discord.ext import commands, tasks
from utils.useful import Embed, Cooldown, send_traceback
from utils.json_loader import read_json

class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache = {}
        self.cache_usage = {}
        self.loops.start()
        self.update_status.start()

    async def expand_tb(self, ctx, error, msg):
        await msg.add_reaction(self.bot.plus)
        await msg.add_reaction(self.bot.minus)
        await msg.add_reaction(self.bot.emoji_dict['save'])

        while True:
            reaction, user = await self.bot.wait_for('reaction_add', check=lambda reaction, m: m == self.bot.owner and reaction.message == msg)
            if str(reaction) == self.bot.plus:
                await send_traceback(self.bot.log_channel, ctx, (True, msg), 3, type(error), error, error.__traceback__)
            elif str(reaction) == self.bot.minus:
                await send_traceback(self.bot.log_channel, ctx, (True, msg), 0, type(error), error, error.__traceback__)
            elif str(reaction) == self.bot.emoji_dict['save']:
                log = self.bot.get_channel(850439592352022528)
                await send_traceback(log, ctx, (False, None), 3, type(error), error, error.__traceback__)
                await msg.channel.send(f"Saved traceback to {log.mention}")

    async def send_error(self, ctx, exc_info: dict):
        em = Embed(
            title=f"{self.bot.emojis_dict('redTick')} Error while running command {exc_info['command']}",
            description=f"```py\n{exc_info['error']}```[Report error](https://discord.gg/nUUJPgemFE)"
        )
        em.set_footer(text="Please report this error in our support server if it persists.")
        await ctx.send(embed=em)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Error handles everything"""
        if ctx.command and ctx.command.has_error_handler(): return
        if isinstance(error, commands.CommandInvokeError):
            error = error.original
            if isinstance(error, discord.errors.Forbidden):
                try:
                    return await ctx.reply(
                        f"{self.bot.emojis_dict('redTick')} I am missing permissions to do that!"
                    )
                except discord.Forbidden:
                    return await ctx.author.send(
                        f"{self.bot.emojis_dict('redTick')} I am missing permissions to do that!"
                    )

        elif isinstance(error, commands.MaxConcurrencyReached):
            return await ctx.send(
                f"{self.bot.emojis_dict('redTick')} The maximum concurrency is already reached for `{ctx.command}` ({error.number}). Try again later."
            )
        elif isinstance(error, wavelink.errors.ZeroConnectedNodes):
            await self.bot.reload_extension("Music")
        elif isinstance(error, commands.CommandOnCooldown):
            command = ctx.command
            default = discord.utils.find(
                lambda c: isinstance(c, Cooldown), command.checks
            ).default_mapping._cooldown.per
            altered = discord.utils.find(
                lambda c: isinstance(c, Cooldown), command.checks
            ).altered_mapping._cooldown.per
            cooldowns = f""
            if default is not None and altered is not None:
                cooldowns += (
                    f"\n\n**Cooldowns:**\nDefault: `{default}s`\nPremium: `{altered}s`"
                )
            em = Embed(
                description=f"You are on cooldown! Try again in **{humanize.precisedelta(dt.timedelta(seconds=error.retry_after), format='%.0f' if error.retry_after > 1 else '%.1f')}**"
                + cooldowns
            )
            return await ctx.send(embed=em)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=ctx.bot.help_command.get_command_help(ctx.command))
            return
        elif isinstance(error, commands.BadArgument):
            return await ctx.send(str(error))
        elif isinstance(error, commands.MissingPermissions):
            return await ctx.send(
                f"{self.bot.emojis_dict('redTick')} You are missing the `{error.missing_perms[0]}` permission to do that!"
            )
        elif isinstance(error, commands.MemberNotFound):
            return await ctx.send(
                f"{self.bot.emojis_dict('redTick')} I couldn't find `{error.argument}`. Have you spelled their name correctly? Try mentioning them."
            )
        elif isinstance(error, commands.RoleNotFound):
            return await ctx.send(
                f"{self.bot.emojis_dict('redTick')} I couldn't find the role `{error.argument}`. Did you spell it correctly? Capitalization matters!"
            )
        elif isinstance(error, commands.CommandNotFound):
            return
        
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("You do not have permissions to use this command!")
            return
        
        exc_info = {
            "command": ctx.command,
            "error": "".join(traceback.format_exception(type(error), error, error.__traceback__, 0)).replace("``", "`\u200b`")
        }
        await self.send_error(ctx, exc_info)
        msg = await send_traceback(self.bot.log_channel, ctx, (False, None), 0, type(error), error, error.__traceback__)
        await self.expand_tb(ctx, error, msg)
        

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        query_a = "INSERT INTO guilds VALUES (?)"
        await self.bot.db.execute(query_a, (guild.id,))
        query_b = "INSERT INTO guild_config (guild_id) VALUES (?)"
        await self.bot.db.execute(query_b, (guild.id,))
        await self.bot.db.commit()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        query_c = "DELETE FROM guilds WHERE guild_id = ?"
        await self.bot.db.execute(query_c, (guild.id,))
        await self.bot.db.commit()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        try:
            self.cache[str(ctx.author.id)] += 1
            self.cache_usage[str(ctx.command.name)] += 1
        except KeyError:
            self.cache[str(ctx.author.id)] = 1
            self.cache_usage[str(ctx.command.name)] = 1

    @tasks.loop(minutes=1)
    async def loops(self):

        await self.bot.change_presence(
            activity=discord.Activity(
                type=0,
                name=f"g.help | {len(self.bot.users)} users | {len(self.bot.guilds)} guilds.",
            )
        )

        for item in self.cache:
            query_user_data = """
                              INSERT INTO users_data (user_id, commands_ran) 
                              VALUES ((?), ?)
                              ON CONFLICT(user_id) DO UPDATE SET commands_ran = commands_ran+?
                              """
            await self.bot.db.execute(
                query_user_data, (int(item), self.cache[item], self.cache[item])
            )
        self.cache = {}

        for item in self.cache_usage:
            query = """
                    INSERT INTO usage (command, counter) 
                    VALUES ((?), ?) 
                    ON CONFLICT(command) DO UPDATE SET counter = counter+?
                    """

            await self.bot.db.execute(
                query, (str(item), self.cache_usage[item], self.cache_usage[item])
            )

        self.cache_usage = {}
        for user in self.bot.cache["users"]:
            query = "UPDATE currency_data SET wallet = ?, bank = ?, max_bank = ?, boost = ?, exp = ?, lvl = ? WHERE user_id = ?"
            await self.bot.db.execute(
                query,
                (
                    self.bot.cache["users"][user]["wallet"],
                    self.bot.cache["users"][user]["bank"],
                    self.bot.cache["users"][user]["max_bank"],
                    round(self.bot.cache["users"][user]["boost"], 2),
                    self.bot.cache["users"][user]["exp"],
                    self.bot.cache["users"][user]["lvl"],
                    user,
                ),
            )

        await self.bot.db.commit()

    @loops.before_loop
    async def before_loops(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=10)
    async def update_status(self):
        status = read_json('config')
        
        groot_status = f"{self.bot.emoji_dict[status['status'].get('groot', 'offline')]} {str.title(status['status'].get('groot', 'offline'))}"
        message = f"**BOT STATUS** \n\n {groot_status} | Groot\n\nRefreshes every second"
    
        em = Embed(
                description=message,
                timestamp=dt.datetime.utcnow()
            )
        em.set_footer(text="Last updated at")
    
        channel = self.bot.get_channel(846450009721012294)
        message = await channel.fetch_message(851052521757081630)
        try:
            await message.edit(embed=em)
        except Exception as error:
            await send_traceback(
                        self.bot.log_channel, 10, type(error), error, error.__traceback__
                    )

    @update_status.before_loop
    async def before_status(self):
        await self.bot.wait_until_ready()

def setup(bot):
    bot.add_cog(Core(bot))
