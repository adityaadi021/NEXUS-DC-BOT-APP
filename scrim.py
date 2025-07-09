import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import re

# Global storage for how-to channels
how_to_channels = {}
scrim_events = {}
scrim_reminders = {}

async def create_how_to_channel(guild):
    """Create or fetch how-to-register channel in Scrims category"""
    if guild.id in how_to_channels:
        return how_to_channels[guild.id]
    
    category = discord.utils.get(guild.categories, name="Scrims")
    if not category:
        category = await guild.create_category("Scrims")
    
    # Check if channel already exists
    how_to_channel = discord.utils.get(category.channels, name="how-to-register")
    if not how_to_channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(send_messages=False)
        }
        how_to_channel = await category.create_text_channel(
            "how-to-register",
            overwrites=overwrites,
            topic="Instructions for registering in scrim events"
        )
        # Post registration guide
        guide = """
        **How to Register for Scrims**
        1. Go to a scrim registration channel
        2. Mention your teammates in ONE message
        Example: `@teammate1 @teammate2 @teammate3`
        3. Bot will automatically register your team
        """
        await how_to_channel.send(guide)
    
    how_to_channels[guild.id] = how_to_channel.id
    return how_to_channel.id

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
            'members': [interaction.guild.get_member(mid).mention for mid in member_ids],
            'member_ids': member_ids  # Store IDs for duplicate checking
        }
        event['teams'].append(team)
        
        # Add team members to the scrim event channel
        guild = interaction.guild
        scrim_channel = guild.get_channel(event['channel_id'])
        if scrim_channel:
            for member_id in member_ids:
                member = guild.get_member(member_id)
                if member:
                    await scrim_channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
        
        # Send public confirmation
        public_view = PublicTeamView(event['event_id'], interaction.user.id)
        await scrim_channel.send(
            f"✅ Team '{self.team_name.value}' registered! Team leader: {interaction.user.mention}\n"
            "Use the button below to view the team.",
            view=public_view
        )
        
        # Send private management view to leader
        try:
            embed = discord.Embed(
                title=f"Team '{self.team_name.value}' Registered",
                description="You can manage your team using the buttons below:",
                color=discord.Color.green()
            )
            await interaction.user.send(embed=embed, view=TeamManageView(event['event_id'], interaction.user.id))
        except discord.Forbidden:
            await interaction.followup.send("I couldn't send you a DM. Please enable DMs to manage your team.", ephemeral=True)
        
        # Update team list in channel
        await update_scrim_team_list(event, interaction.client)
        
        # Check if slots filled
        if len(event['teams']) >= event['slots']:
            await notify_scrim_organizer(event, interaction.client)

class PublicTeamView(View):
    def __init__(self, event_id, team_leader_id):
        super().__init__(timeout=None)
        self.add_item(ViewTeamButton(event_id, team_leader_id))

class TeamManageView(View):
    def __init__(self, event_id, team_leader_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.team_leader_id = team_leader_id
        self.add_item(ChangeTeamNameButton(event_id, team_leader_id))
        self.add_item(CancelSlotButton(event_id, team_leader_id))
        self.add_item(ViewTeamButton(event_id, team_leader_id))

class ChangeTeamNameButton(Button):
    def __init__(self, event_id, team_leader_id):
        super().__init__(label="Change Team Name", style=discord.ButtonStyle.primary)
        self.event_id = event_id
        self.team_leader_id = team_leader_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.team_leader_id:
            await interaction.response.send_message("❌ Only the team leader can change the team name.", ephemeral=True)
            return
        await interaction.response.send_modal(ChangeTeamNameModal(self.event_id, self.team_leader_id))

class ChangeTeamNameModal(Modal, title="Change Team Name"):
    def __init__(self, event_id, team_leader_id):
        super().__init__()
        self.event_id = event_id
        self.team_leader_id = team_leader_id
        self.team_name = TextInput(label="New Team Name", required=True, max_length=32)
        self.add_item(self.team_name)
    
    async def on_submit(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ Scrim event not found.", ephemeral=True)
            return
        
        team = next((t for t in event['teams'] if t['captain_id'] == self.team_leader_id), None)
        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return
        
        if any(t['team_name'].lower() == self.team_name.value.lower() for t in event['teams'] if t != team):
            await interaction.response.send_message("❌ Team name already taken.", ephemeral=True)
            return
        
        team['team_name'] = self.team_name.value
        await interaction.response.send_message(f"✅ Team name changed to {self.team_name.value}", ephemeral=True)
        await update_scrim_team_list(event, interaction.client)

class CancelSlotButton(Button):
    def __init__(self, event_id, team_leader_id):
        super().__init__(label="Cancel My Slot", style=discord.ButtonStyle.danger)
        self.event_id = event_id
        self.team_leader_id = team_leader_id
    
    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.team_leader_id:
                await interaction.response.send_message("❌ Only the team leader can cancel the slot.", ephemeral=True)
                return
            
            event = scrim_events.get(self.event_id)
            if not event:
                await interaction.response.send_message("❌ Scrim event not found.", ephemeral=True)
                return
            
            team = next((t for t in event['teams'] if t['captain_id'] == self.team_leader_id), None)
            if not team:
                await interaction.response.send_message("❌ Team not found.", ephemeral=True)
                return
            
            # Remove permissions first
            scrim_channel = interaction.guild.get_channel(event['channel_id'])
            if scrim_channel:
                for member_id in team['member_ids']:
                    member = interaction.guild.get_member(member_id)
                    if member:
                        try:
                            await scrim_channel.set_permissions(member, overwrite=None)
                        except discord.NotFound:
                            pass  # Channel might be deleted
            
            # Then remove team from event
            event['teams'].remove(team)
            await interaction.response.send_message("✅ Your team slot has been cancelled.", ephemeral=True)
            await update_scrim_team_list(event, interaction.client)
            
            # If slots were full and now aren't, update status
            if len(event['teams']) < event['slots'] and event.get('slots_filled'):
                event['slots_filled'] = False
                scrim_channel = interaction.guild.get_channel(event['channel_id'])
                if scrim_channel:
                    await scrim_channel.send(f"⚠️ Slot available! Teams registered: {len(event['teams'])}/{event['slots']}")
            
        except Exception as e:
            print(f"Error in CancelSlotButton: {e}")
            await interaction.response.send_message("❌ An error occurred. Please try again later.", ephemeral=True)

class ViewTeamButton(Button):
    def __init__(self, event_id, team_leader_id):
        super().__init__(label="View Team", style=discord.ButtonStyle.secondary)
        self.event_id = event_id
        self.team_leader_id = team_leader_id
    
    async def callback(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ Scrim event not found.", ephemeral=True)
            return
        
        team = next((t for t in event['teams'] if t['captain_id'] == self.team_leader_id), None)
        if not team:
            await interaction.response.send_message("❌ Team not found.", ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f"Team: {team['team_name']}",
            description=", ".join(team['members']),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
    embed.set_footer(text=f"Teams: {len(event['teams'])}/{event['slots']}")
    
    if event.get('team_list_msg_id'):
        try:
            msg = await channel.fetch_message(event['team_list_msg_id'])
            await msg.edit(embed=embed)
        except:
            msg = await channel.send(embed=embed)
            event['team_list_msg_id'] = msg.id
    else:
        msg = await channel.send(embed=embed)
        event['team_list_msg_id'] = msg.id

async def create_organizer_channel(event, bot):
    """Create private channel for organizer and admins"""
    guild = bot.get_guild(int(event['event_id'].split('-')[0]))
    if not guild:
        return None
    
    # Find or create Scrims category
    category = discord.utils.get(guild.categories, name="Scrims")
    if not category:
        category = await guild.create_category("Scrims")
    
    # Find Scrim Mod role
    scrim_mod_role = discord.utils.get(guild.roles, name="Scrim Mod")
    
    # Create permission overwrites
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    
    # Add organizer
    organizer = guild.get_member(event['organizer_id'])
    if organizer:
        overwrites[organizer] = discord.PermissionOverwrite(view_channel=True)
    
    # Add Scrim Mod role if exists
    if scrim_mod_role:
        overwrites[scrim_mod_role] = discord.PermissionOverwrite(view_channel=True)
    
    # Add admins
    for member in guild.members:
        if member.guild_permissions.administrator:
            overwrites[member] = discord.PermissionOverwrite(view_channel=True)
    
    # Create channel
    channel_name = f"scrim-admin-{event['event_name'][:20].lower().replace(' ', '-')}"
    try:
        channel = await category.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            topic=f"Admin channel for {event['event_name']}"
        )
        return channel
    except Exception as e:
        print(f"Error creating organizer channel: {e}")
        return None

async def notify_scrim_organizer(event, bot):
    """Notify organizer AND channel when slots fill and create private channel"""
    # 1. Announce in scrim channel first
    channel = bot.get_channel(event['channel_id'])
    if channel:
        event['slots_filled'] = True
        await channel.send("🎉 **All slots filled!** Organizer is setting the scrim time...")
    
    # 2. Create private channel for organizer and admins
    organizer_channel = await create_organizer_channel(event, bot)
    if not organizer_channel:
        try:
            organizer = await bot.fetch_user(event['organizer_id'])
            await organizer.send(f"Failed to create admin channel for '{event['event_name']}'.")
        except:
            pass
        return
    
    # Store channel ID in event
    event['organizer_channel_id'] = organizer_channel.id
    
    # 3. Send message with time setting button
    embed = discord.Embed(
        title=f"🏆 {event['event_name']} - All Slots Filled!",
        description="Click the button below to set the scrim start time and details.",
        color=discord.Color.gold()
    )
    view = SetScrimTimeView(event['event_id'])
    await organizer_channel.send(embed=embed, view=view)

class SetScrimTimeView(View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.add_item(SetScrimTimeButton(event_id))

class SetScrimTimeButton(Button):
    def __init__(self, event_id):
        super().__init__(label="Set Scrim Time", style=discord.ButtonStyle.primary)
        self.event_id = event_id
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ScrimTimeModal(self.event_id))

class ScrimTimeModal(Modal, title="Set Scrim Time"):
    def __init__(self, event_id):
        super().__init__()
        self.event_id = event_id
        self.scrim_time = TextInput(
            label="Scrim Start Time (e.g. 10-07-2025 18:30)",
            placeholder="DD-MM-YYYY HH:MM (24h format, IST timezone)",
            required=True
        )
        self.scrim_details = TextInput(
            label="Scrim Details (format, rules, etc.)",
            style=discord.TextStyle.long,
            required=True,
            placeholder="Example: BO3, Map Pool: Bind, Haven, Split...",
            max_length=1000
        )
        self.add_item(self.scrim_time)
        self.add_item(self.scrim_details)
    
    async def on_submit(self, interaction: discord.Interaction):
        event = scrim_events.get(self.event_id)
        if not event:
            await interaction.response.send_message("❌ Scrim event not found.", ephemeral=True)
            return
        
        # Parse and validate time (IST format)
        time_str = self.scrim_time.value
        try:
            # Parse DD-MM-YYYY HH:MM
            dt = datetime.strptime(time_str, "%d-%m-%Y %H:%M")
            # Convert to UTC (IST is UTC+5:30)
            utc_time = dt - timedelta(hours=5, minutes=30)
            if utc_time < datetime.utcnow():
                raise ValueError("Time must be in future")
        except Exception as e:
            await interaction.response.send_message(
                "❌ Invalid time format or time in past. Use DD-MM-YYYY HH:MM (24h format, IST timezone)",
                ephemeral=True
            )
            return
        
        event['scrim_time'] = dt.strftime("%d-%m-%Y %H:%M IST")
        event['scrim_details'] = self.scrim_details.value
        event['scrim_utc'] = utc_time
        
        # Announce in scrim channel
        scrim_channel = interaction.guild.get_channel(event['channel_id'])
        if scrim_channel:
            # Mention all registered members
            all_member_ids = set()
            for team in event['teams']:
                for member_id in team['member_ids']:
                    all_member_ids.add(member_id)
            
            mentions = " ".join([f"<@{mid}>" for mid in all_member_ids])
            
            embed = discord.Embed(
                title=f"🏆 {event['event_name']} - Scrim Scheduled!",
                description=(
                    f"**Start Time:** {event['scrim_time']}\n"
                    f"**Details:**\n{self.scrim_details.value}\n\n"
                    f"{mentions}"
                ),
                color=discord.Color.green()
            )
            await scrim_channel.send(embed=embed)
            
            # Set reminder
            await schedule_scrim_reminder(event, interaction.client)
        
        # Notify in organizer channel
        await interaction.response.send_message(
            f"✅ Scrim time set to {event['scrim_time']}\n"
            f"Reminder scheduled for all participants.",
            ephemeral=False
        )

async def schedule_scrim_reminder(event, bot):
    """Schedule a reminder 30 minutes before scrim start"""
    if 'scrim_utc' not in event:
        return
    
    reminder_time = event['scrim_utc'] - timedelta(minutes=30)
    now = datetime.utcnow()
    
    if reminder_time < now:
        return  # Skip if reminder time already passed
    
    delay = (reminder_time - now).total_seconds()
    
    # Store task for later cancellation if needed
    event_id = event['event_id']
    
    async def send_reminder():
        await asyncio.sleep(delay)
        
        # Check if event still exists
        event = scrim_events.get(event_id)
        if not event:
            return
        
        channel = bot.get_channel(event['channel_id'])
        if not channel:
            return
        
        # Mention all registered members
        all_member_ids = set()
        for team in event['teams']:
            for member_id in team['member_ids']:
                all_member_ids.add(member_id)
        
        mentions = " ".join([f"<@{mid}>" for mid in all_member_ids])
        
        embed = discord.Embed(
            title=f"⏰ {event['event_name']} - Starting Soon!",
            description=(
                f"**Scrim starts in 30 minutes!**\n"
                f"**Start Time:** {event['scrim_time']}\n\n"
                f"{mentions}"
            ),
            color=discord.Color.gold()
        )
        await channel.send(embed=embed)
    
    # Store and run task
    task = asyncio.create_task(send_reminder())
    scrim_reminders[event_id] = task

async def setup(bot):
    print("Scrim commands setup started...")
    
    def is_flasherx7(interaction):
        return interaction.user.name == "flasherx7"
    
    def is_admin_or_permitted(interaction):
        if interaction.user.guild_permissions.administrator:
            return True
        permitted_roles = ["Scrim Admin", "Event Manager"]
        user_roles = [role.name for role in interaction.user.roles]
        return any(role in permitted_roles for role in user_roles)

    @bot.tree.command(name="add-scrim-event", description="Create a new scrim registration event")
    @app_commands.describe(
        slots="Number of teams allowed to register",
        team_size="Number of members per team (including captain)",
        event_name="Title of the scrim event",
        description="Description for the scrim event"
    )
    async def add_scrim_event(
        interaction: discord.Interaction,
        slots: int,
        team_size: Optional[int] = 4,
        event_name: Optional[str] = "Scrim Event",
        description: Optional[str] = "Register your team for the scrim!"
    ):
        print(f"Add scrim event command received from {interaction.user}")
        
        if not (interaction.user.guild_permissions.manage_guild or 
                interaction.user.guild_permissions.administrator or 
                is_flasherx7(interaction)):
            return await interaction.response.send_message(
                "❌ You need 'Administrator' permission to create a scrim event.", 
                ephemeral=True
            )
        
        guild = interaction.guild
        await create_how_to_channel(guild)
        
        category = None
        for cat in guild.categories:
            if cat.name.lower().startswith("scrims"):
                category = cat
                break
        if not category:
            category = await guild.create_category("Scrims")
        
        reg_channel_name = f"register-for-{event_name.replace(' ', '-')[:20].lower()}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(send_messages=True, manage_messages=True)
        }
        
        try:
            reg_channel = await guild.create_text_channel(
                reg_channel_name,
                overwrites=overwrites,
                category=category,
                topic=f"Registration channel for {event_name}"
            )
        except Exception as e:
            print(f"Error creating channel: {e}")
            return await interaction.response.send_message(
                "❌ Failed to create registration channel. Please check my permissions.",
                ephemeral=True
            )
        
        event_id = f"{guild.id}-{int(datetime.utcnow().timestamp())}"
        scrim_events[event_id] = {
            'event_id': event_id,
            'event_name': event_name,
            'description': description,
            'channel_id': reg_channel.id,
            'slots': slots,
            'team_size': team_size,
            'organizer_id': interaction.user.id,
            'teams': [],
            'team_list_msg_id': None,
            'scrim_time': None,
            'organizer_channel_id': None,
            'slots_filled': False
        }
        
        embed = discord.Embed(
            title=f"🏆 {event_name} Registration",
            description=(
                f"{description}\n\nSlots: {slots}\nTeam size: {team_size}\n\n"
                "To register, mention your team members in this channel (e.g. @user1 @user2 @user3).\n"
                "The message sender will be the team leader.\n"
                "After registration, you can manage your team using the buttons provided."
            ),
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        
        try:
            await reg_channel.send(embed=embed)
            await interaction.response.send_message(
                f"✅ Scrim registration started in {reg_channel.mention}", 
                ephemeral=True
            )
        except Exception as e:
            print(f"Error sending initial messages: {e}")
            await interaction.response.send_message(
                "❌ Failed to send initial messages. Please check my permissions.",
                ephemeral=True
            )

    class StartTeamNameModalButton(View):
        def __init__(self, event_id, member_ids):
            super().__init__(timeout=60)
            self.add_item(self.TeamNameButton(event_id, member_ids))
        
        class TeamNameButton(Button):
            def __init__(self, event_id, member_ids):
                super().__init__(label="Enter Team Name", style=discord.ButtonStyle.primary)
                self.event_id = event_id
                self.member_ids = member_ids
            
            async def callback(self, interaction: discord.Interaction):
                await interaction.response.send_modal(TeamNameModal(self.event_id, self.member_ids))
    
    @bot.event
    async def on_message(message):
        if message.author.bot:
            return
        
        # Check if this is a registration channel
        for event_id, event in scrim_events.items():
            if message.channel.id == event['channel_id']:
                # Allow commands to pass through
                ctx = await bot.get_context(message)
                if ctx.valid:
                    await bot.invoke(ctx)
                    return
                
                # Check if user has admin permissions
                if message.author.guild_permissions.administrator:
                    return
                
                # Check for permitted roles
                permitted_roles = ["Scrim Admin", "Event Manager"]
                user_roles = [role.name for role in message.author.roles]
                if any(role in permitted_roles for role in user_roles):
                    return
                
                # Process registration message
                mentions = [m for m in message.mentions if not m.bot and m != message.author]
                required_mentions = event['team_size'] - 1
                
                # Validate registration message
                if len(mentions) != required_mentions:
                    try:
                        await message.delete()
                        guide = (
                            f"❌ Invalid registration in {message.channel.mention}. "
                            f"You need to mention exactly {required_mentions} teammates (excluding yourself).\n"
                            f"Example: {' '.join([f'@{message.author.name}'] + [f'@teammate{i+1}' for i in range(required_mentions)])}"
                        )
                        await message.author.send(guide, delete_after=30)
                    except discord.Forbidden:
                        try:
                            await message.channel.send(
                                f"{message.author.mention} Please check your DMs for registration instructions.",
                                delete_after=10
                            )
                        except:
                            pass
                    return
                
                # Check if user is already registered
                if any(message.author.id in t['member_ids'] for t in event['teams']):
                    try:
                        await message.delete()
                        await message.author.send(
                            "❌ You are already registered in this event.",
                            delete_after=15
                        )
                    except discord.Forbidden:
                        pass
                    return
                
                # Check if any mentioned user is already registered
                mentioned_ids = [m.id for m in mentions]
                for team in event['teams']:
                    if any(mid in team['member_ids'] for mid in mentioned_ids):
                        try:
                            await message.delete()
                            await message.author.send(
                                "❌ One or more mentioned users are already registered.",
                                delete_after=15
                            )
                        except discord.Forbidden:
                            pass
                        return
                
                # Check for duplicate mentions
                if len(set(mentioned_ids)) != len(mentions):
                    try:
                        await message.delete()
                        await message.author.send(
                            "❌ You mentioned the same user multiple times.",
                            delete_after=15
                        )
                    except discord.Forbidden:
                        pass
                    return
                
                # All checks passed - proceed with registration
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                
                # Send team name modal via button
                try:
                    view = StartTeamNameModalButton(event_id, [str(m.id) for m in mentions])
                    await message.channel.send(
                        f"{message.author.mention}, click the button below to submit your team name:",
                        view=view,
                        delete_after=60
                    )
                except:
                    await message.channel.send(
                        f"{message.author.mention}, an error occurred during registration. Please try again later.",
                        delete_after=15
                    )
                
                return
        
        await bot.process_commands(message)

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
            status = "✅ Slots Filled" if len(event['teams']) >= event['slots'] else f"🟢 {len(event['teams'])}/{event['slots']} slots"
            embed.add_field(
                name=f"{i}. {event['event_name']} - {status}",
                value=(
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
        if not (interaction.user.guild_permissions.manage_guild or 
                interaction.user.guild_permissions.administrator or 
                is_flasherx7(interaction)):
            return await interaction.response.send_message(
                "❌ You need 'Administrator' permission to remove a scrim event.", 
                ephemeral=True
            )
        
        event = scrim_events.get(event_id)
        if not event or not str(event_id).startswith(str(interaction.guild.id)):
            return await interaction.response.send_message("❌ Event not found or not in this server.", ephemeral=True)
        
        # Cancel any scheduled reminders
        if event_id in scrim_reminders:
            scrim_reminders[event_id].cancel()
            del scrim_reminders[event_id]
        
        # Delete organizer channel if exists
        if event.get('organizer_channel_id'):
            try:
                channel = interaction.guild.get_channel(event['organizer_channel_id'])
                if channel:
                    await channel.delete(reason="Scrim event removed")
            except:
                pass
        
        # Delete registration channel
        try:
            channel = interaction.guild.get_channel(event['channel_id'])
            if channel:
                await channel.delete(reason="Scrim event removed")
        except:
            pass
        
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

    print("Scrim commands setup completed successfully")
