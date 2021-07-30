import io
import re
import traceback

import aiohttp
import discord
import imagehash
from discord.ext import commands
from PIL import Image as PILImage
from styrobot.util import auth, database, misc
from styrobot.util import message as message_util
from wand.image import Image


class RepostCog(commands.Cog):
    """
    Reposts are enabled by specifying channel ID's in the reposts.channel setting,
    each channel separated by commas.
    """
    def __init__(self, bot):
        self.bot = bot
        self.conn_cache = {}
        self.repost_cache = {}
    
    def conn_for_guild(self, id):
        if id in self.conn_cache:
            return self.conn_cache[id]
        ret = database.open_guild_database(id)
        self.conn_cache[id] = ret
        ret.execute('CREATE TABLE IF NOT EXISTS reposts (hash text, link text UNIQUE)')
        ret.commit()
        cur = ret.cursor()
        cur.execute('SELECT hash FROM reposts')
        self.repost_cache[id] = [self.load_hash(x[0]) for x in cur.fetchall()]
        return ret
    
    def load_hash(self, x):
        return imagehash.hex_to_hash(x)
        
    def add_hash(self, guild_id, x, link):
        con = self.conn_for_guild(guild_id)
        con.execute('INSERT INTO reposts VALUES (?,?)', (str(x), link))
        con.commit()
        self.repost_cache[guild_id].append(x)

    async def check_repost(self, image: Image, message):   
        image.resize(2048, 2048)
        # this should clear up empty space in an image
        image.liquid_rescale(1024, 1024)
        i = PILImage.open(io.BytesIO(image.make_blob('jpeg')))
        misc.incinerate(i)
        h = imagehash.whash(i)
        if len(self.repost_cache[message.guild.id]) > 0:
            best = min(self.repost_cache[message.guild.id], key=lambda x: h-x)
            if (best is not None) and (h - best < 8):
                cur = self.conn_for_guild(message.guild.id).cursor()
                cur.execute('SELECT link FROM reposts WHERE hash=?', (str(best),))
                link = cur.fetchone()[0]
                await message.reply(f'Repost! (distance {h-best}): {link}')
        self.add_hash(message.guild.id, h, message.jump_url)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            # we don't care about bot messages
            return
        if not message.guild:
            # we don't care about DMs
            return
        conn = self.conn_for_guild(message.guild.id)
        channels = database.get_guild_setting(None, 'reposts.channel', con=conn, default='').split(',')
        if str(message.channel.id) not in channels:
            # not in the right channel
            return
        
        images = await message_util.get_images(message, attempts=8)
        
        if len(images) == 0:
            # nothing interesting
            return
        
        for image in images:
            await self.check_repost(image, message)
    
    @commands.command(name='repost.clear')
    async def repost_clear(self, ctx: commands.Context):
        """
        Clear the repost database.
        """
        if not ctx.guild:
            return
        conn = self.conn_for_guild(ctx.guild.id)
        if not auth.is_authorized(ctx.author, con=conn):
            await ctx.send('Not authorized.')
            return
        conn.execute('DELETE FROM reposts')
        conn.commit()
        self.repost_cache[ctx.guild.id] = []
        await ctx.send('Cleared reposts database.')
        return


def setup(bot):
    bot.add_cog(RepostCog(bot))
