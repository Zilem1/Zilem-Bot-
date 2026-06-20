import discord
from discord.ext import commands
from discord import app_commands

class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="announcement", description="Send an announcement")
    @app_commands.describe(
        message="The announcement text",
        title="Embed title (optional)",
        channel="Channel to send to (optional)",
        ping="Who to ping"
    )
    @app_commands.choices(ping=[
        app_commands.Choice(name="@everyone", value="everyone"),
        app_commands.Choice(name="@here",     value="here"),
        app_commands.Choice(name="None",      value="none"),
    ])
    @app_commands.default_permissions(manage_messages=True)
    async def announcement(
        self,
        interaction: discord.Interaction,
        message: str,
        title: str = "📢 Announcement",
        channel: discord.TextChannel = None,
        ping: str = "none"
    ):
        target = channel or interaction.channel

        embed = discord.Embed(
            title=title,
            description=message,
            color=0x7c3aed  # Zilem purple
        )
        embed.set_footer(text=f"Announced by {interaction.user}")
        embed.timestamp = discord.utils.utcnow()

        ping_text = f"@{ping}" if ping != "none" else None

        try:
            await target.send(content=ping_text, embed=embed)
            await interaction.response.send_message(
                f"✅ Sent to {target.mention}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Failed: {e}", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Announcement(bot))
