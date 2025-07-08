import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
from datetime import datetime
from typing import Optional
import asyncio

# In-memory storage for scrim events (replace with persistent storage if needed)
scrim_events = {}

class ScrimRegistrationModal(Modal, title="Scrim Team Registration"):
    def __init__(self, event_id, team_size):
        super().__init__()
        self.event_id = event_id
        self.team_size = team_size
        self.team_name = TextInput(label="Team Name", required=True, max_length=32)
        self.members = TextInput(label=f"Team Members (mention {team_size-1} others)", required=True, placeholder="@member1 @member2 ...")
        self.add_item(self.team_name)
        self.add_item(self.members)

    async def on_submit(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ This scrim event is no longer active.", ephemeral=True)
            return
        # Validate team name uniqueness
        if any(t['team_name'].lower() == self.team_name.value.lower() for t in event['teams']):
            await interaction.response.send_message("❌ Team name already registered.", ephemeral=True)
            return
        # Validate member mentions
        mentions = [m for m in self.members.value.split() if m.startswith('<@')]
        if len(mentions) != self.team_size - 1:
            await interaction.response.send_message(f"❌ Please mention exactly {self.team_size-1} team members.", ephemeral=True)
            return
        # Register team
        team = {
            'team_name': self.team_name.value,
            'captain_id': interaction.user.id,
            'members': [interaction.user.mention] + mentions
        }
        event['teams'].append(team)
        await interaction.response.send_message(f"✅ Team '{self.team_name.value}' registered!", ephemeral=True)
        # Update team list in channel
        await update_scrim_team_list(event, interaction.client)
        # Check if slots filled
        if len(event['teams']) >= event['slots']:
            await notify_scrim_organizer(event, interaction.client)

class ScrimRegisterButton(Button):
    def __init__(self, event_id):
        super().__init__(label="Register Team", style=discord.ButtonStyle.primary, custom_id=f"scrim_register_{event_id}")
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ This scrim event is no longer active.", ephemeral=True)
            return
        # Check if user already registered
        for t in event['teams']:
            if interaction.user.id == t['captain_id'] or interaction.user.mention in t['members']:
                await interaction.response.send_message("❌ You are already registered in a team for this event.", ephemeral=True)
                return
        await interaction.response.send_modal(ScrimRegistrationModal(self.event_id, event['team_size']))

class ScrimRegisterView(View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.add_item(ScrimRegisterButton(event_id))

async def update_scrim_team_list(event, bot):
    channel = bot.get_channel(event['channel_id'])
    if not channel:
        return
    team_list = '\n'.join([f"{i+1}. {t['team_name']} ({', '.join(t['members'])})" for i, t in enumerate(event['teams'])]) or "No teams registered yet."
    embed = discord.Embed(
        title=f"🏆 {event['event_name']} - Registered Teams",
        description=team_list,
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    if event.get('team_list_msg_id'):
        try:
            msg = await channel.fetch_message(event['team_list_msg_id'])
            await msg.edit(embed=embed)
        except Exception:
            msg = await channel.send(embed=embed)
            event['team_list_msg_id'] = msg.id
    else:
        msg = await channel.send(embed=embed)
        event['team_list_msg_id'] = msg.id

async def notify_scrim_organizer(event, bot):
    user = await bot.fetch_user(event['organizer_id'])
    if not user:
        return
    class ScrimTimeModal(Modal, title="Set Scrim Time"):
        scrim_time = TextInput(label="Scrim Start Time (e.g. 2025-07-10 18:30)", required=True)
        async def on_submit(self, interaction: discord.Interaction):
            event['scrim_time'] = self.scrim_time.value
            channel = bot.get_channel(event['channel_id'])
            if channel:
                embed = discord.Embed(
                    title=f"🏆 {event['event_name']} - Scrim Scheduled!",
                    description=f"All slots filled!\n\n**Scrim Time:** {self.scrim_time.value}",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                await channel.send(embed=embed)
            await interaction.response.send_message("✅ Scrim time set and announced!", ephemeral=True)
    await user.send(f"All slots for your scrim event '{event['event_name']}' are filled! Please set the scrim time:")
    await user.send_modal(ScrimTimeModal())

def setup_scrim_commands(bot):
    @bot.tree.command(name="add-scrim-event", description="Create a new scrim registration event")
    @app_commands.describe(
        channel="Channel to post the registration message",
        slots="Number of teams allowed to register",
        team_size="Number of members per team (including captain)",
        event_name="Name of the scrim event"
    )
    async def add_scrim_event(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        slots: int,
        team_size: Optional[int] = 4,
        event_name: Optional[str] = "Scrim Event"
    ):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "❌ You need 'Manage Server' permission to create a scrim event.", ephemeral=True
            )
        event_id = f"{interaction.guild.id}-{int(datetime.utcnow().timestamp())}"
        scrim_events[event_id] = {
            'event_id': event_id,
            'event_name': event_name,
            'channel_id': channel.id,
            'slots': slots,
            'team_size': team_size,
            'organizer_id': interaction.user.id,
            'teams': [],
            'team_list_msg_id': None,
            'scrim_time': None
        }
        embed = discord.Embed(
            title=f"🏆 {event_name} Registration",
            description=(
                f"Slots: {slots}\nTeam size: {team_size}\n\n"
                "Click the button below to register your team!\n"
                "- You will be asked for your team name and to mention your teammates.\n"
                "- Each user can only register for one team.\n"
                "- When all slots are filled, the organizer will be notified to set the scrim time."
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        view = ScrimRegisterView(event_id)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Scrim registration started in {channel.mention}", ephemeral=True)
