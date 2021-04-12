import re
from typing import Optional

from aiohttp import ClientSession, ClientError
from discord import Guild, TextChannel, Message, Embed
from discord.ext import commands
from discord.ext.commands import guild_only, Context, CommandError, UserInputError

from PyDrocsid.cog import Cog
from PyDrocsid.database import db, filter_by
from PyDrocsid.events import StopEventHandling
from PyDrocsid.translations import t
from PyDrocsid.util import send_long_embed, reply, docs
from .colors import Colors
from .models import MediaOnlyChannel
from .permissions import MediaOnlyPermission
from ...contributor import Contributor
from ...pubsub import send_to_changelog, can_respond_on_reaction, send_alert

tg = t.g
t = t.mediaonly


async def contains_image(message: Message) -> bool:
    urls = [(att.url,) for att in message.attachments]
    urls += re.findall(r"(https?://([a-zA-Z0-9\-_~]+\.)+[a-zA-Z0-9\-_~]+(/\S*)?)", message.content)
    for url, *_ in urls:
        try:
            async with ClientSession() as session, session.head(url) as response:
                mime = response.headers["Content-type"]
        except (KeyError, AttributeError, UnicodeError, ConnectionError, ClientError):
            break

        if mime.startswith("image/"):
            return True

    return False


async def delete_message(message: Message):
    await message.delete()

    embed = Embed(title=t.mediaonly, description=t.deleted_nomedia, colour=Colors.error)
    await message.channel.send(content=message.author.mention, embed=embed, delete_after=30)

    await send_alert(message.guild, t.log_deleted_nomedia(message.author.mention, message.channel.mention))


class MediaOnlyCog(Cog, name="MediaOnly"):
    CONTRIBUTORS = [Contributor.Defelo, Contributor.wolflu]

    @can_respond_on_reaction.subscribe
    async def handle_can_respond_on_reaction(self, channel: TextChannel) -> bool:
        return not await db.exists(filter_by(MediaOnlyChannel, channel=channel.id))

    async def on_message(self, message: Message):
        if message.guild is None or message.author.bot:
            return
        if await MediaOnlyPermission.bypass.check_permissions(message.author):
            return
        if not await MediaOnlyChannel.exists(message.channel.id):
            return
        if await contains_image(message):
            return

        await delete_message(message)
        raise StopEventHandling

    @commands.group(aliases=["mo"])
    @MediaOnlyPermission.read.check
    @guild_only()
    @docs(t.commands.mediaonly)
    async def mediaonly(self, ctx: Context):
        if ctx.invoked_subcommand is None:
            raise UserInputError

    @mediaonly.command(name="list", aliases=["l", "?"])
    @docs(t.commands.list)
    async def mediaonly_list(self, ctx: Context):
        guild: Guild = ctx.guild
        out = []
        async for channel in MediaOnlyChannel.stream():
            text_channel: Optional[TextChannel] = guild.get_channel(channel)
            if not text_channel:
                await MediaOnlyChannel.remove(channel)
                continue

            out.append(f":small_orange_diamond: {text_channel.mention}")

        embed = Embed(title=t.media_only_channels_header, colour=Colors.error)
        if out:
            embed.colour = Colors.MediaOnly
            embed.description = "\n".join(out)
            await send_long_embed(ctx, embed)
        else:
            embed.description = t.no_media_only_channels
            await reply(ctx, embed=embed)

    @mediaonly.command(name="add", aliases=["a", "+"])
    @MediaOnlyPermission.write.check
    @docs(t.commands.add)
    async def mediaonly_add(self, ctx: Context, channel: TextChannel):
        if await MediaOnlyChannel.exists(channel.id):
            raise CommandError(t.channel_already_media_only)
        if not channel.permissions_for(channel.guild.me).manage_messages:
            raise CommandError(t.media_only_not_changed_no_permissions)

        await MediaOnlyChannel.add(channel.id)
        embed = Embed(
            title=t.media_only_channels_header,
            description=t.channel_now_media_only,
            colour=Colors.MediaOnly,
        )
        await reply(ctx, embed=embed)
        await send_to_changelog(ctx.guild, t.log_channel_now_media_only(channel.mention))

    @mediaonly.command(name="remove", aliases=["del", "r", "d", "-"])
    @MediaOnlyPermission.write.check
    @docs(t.commands.remove)
    async def mediaonly_remove(self, ctx: Context, channel: TextChannel):
        if not await MediaOnlyChannel.exists(channel.id):
            raise CommandError(t.channel_not_media_only)

        await MediaOnlyChannel.remove(channel.id)
        embed = Embed(
            title=t.media_only_channels_header,
            description=t.channel_not_media_only_anymore,
            colour=Colors.MediaOnly,
        )
        await reply(ctx, embed=embed)
        await send_to_changelog(ctx.guild, t.log_channel_not_media_only_anymore(channel.mention))
