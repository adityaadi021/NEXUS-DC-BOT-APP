import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Select
import os
import json
from datetime import datetime, timedelta
from typing import Optional
import asyncio
import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask
from threading import Thread
import scrim
from PIL import Image, ImageDraw, ImageFont
import io
import sys

print("🚀 Bot is starting...")

# Flask setup
app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

@app.route('/health')
def health_check():
    return 'OK', 200

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Get token from environment
token = os.getenv("DISCORD_TOKEN")
if not token:
    print("❌ CRITICAL ERROR: Missing DISCORD_TOKEN")
    exit(1)

# YouTube API setup
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
youtube_service = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY) if YOUTUBE_API_KEY else None

# Configure intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents
)

# Global command sync flag
commands_synced = False

# Configuration storage
CONFIG_FILE = "bot_config.json"
guild_configs = {}
EVENT_FILE = "event_schedule.json"
event_schedule = {}
SOCIAL_FILE = "social_trackers.json"
social_trackers = {}
active_team_collections = {}

# Helper functions
def create_embed(title: str = None, description: str = None, color: discord.Color = discord.Color(0x3e0000)) -> discord.Embed:
    """Helper function to create consistent embeds"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
    return embed

def has_announcement_permission(interaction: discord.Interaction) -> bool:
    """Check if user has announcement permissions through role or manage_messages"""
    if not interaction.guild:
        return False
    
    guild_id = str(interaction.guild.id)
    
    if interaction.user.guild_permissions.manage_messages:
        return True
    
    if interaction.user.id == interaction.guild.owner_id:
        return True
    
    if guild_id in guild_configs:
        role_id = guild_configs[guild_id].get("announcement_role")
        if role_id:
            return any(role.id == role_id for role in interaction.user.roles)
    
    return False

# Config loading/saving functions
def load_config():
    global guild_configs
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                guild_configs = json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading config: {e}")
        guild_configs = {}

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(guild_configs, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving config: {e}")

def load_event_schedule():
    global event_schedule
    try:
        if os.path.exists(EVENT_FILE):
            with open(EVENT_FILE, 'r') as f:
                event_schedule = json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading event schedule: {e}")
        event_schedule = {}

def save_event_schedule():
    try:
        with open(EVENT_FILE, 'w') as f:
            json.dump(event_schedule, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving event schedule: {e}")

def load_social_trackers():
    global social_trackers
    try:
        if os.path.exists(SOCIAL_FILE):
            with open(SOCIAL_FILE, 'r') as f:
                social_trackers = json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading social trackers: {e}")
        social_trackers = {}

def save_social_trackers():
    try:
        with open(SOCIAL_FILE, 'w') as f:
            json.dump(social_trackers, f, indent=2)
    except Exception as e:
        print(f"⚠️ Error saving social trackers: {e}")


DEFAULT_WELCOME_MESSAGE = """
Hey {member}!,

🔹 Welcome to Nexus Esports 🔹

First click on Nexus Esports above
and select 'Show All Channels' so that
all channels become visible to you.
and get yourself ✅verified by clicking on the
#verify channel.
"""

DEFAULT_BANNER_URL = "https://cdn.discordapp.com/attachments/1378018158010695722/1378426905585520901/standard_2.gif"



# Bot events
@bot.event
async def on_ready():
    global commands_synced
    print(f"✅ Bot ready! Logged in as {bot.user}")
    
    invite_url = discord.utils.oauth_url(
        bot.user.id,
        permissions=discord.Permissions(
            send_messages=True,
            embed_links=True,
            view_channel=True,
            read_message_history=True,
            mention_everyone=True,
            manage_messages=True,
            attach_files=True
        ),
        scopes=("bot", "applications.commands")
    )
    print(f"\n🔗 Add bot to other servers using this link (MUST include 'applications.commands' scope):\n{invite_url}\n")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game('Watching')
    )
    
    if not commands_synced:
        try:
            synced = await bot.tree.sync()
            commands_synced = True
            print(f"✅ Synced {len(synced)} command(s) globally")
        except Exception as e:
            print(f"❌ Command sync failed: {e}")
    
    if not hasattr(bot, 'social_task'):
        bot.social_task = bot.loop.create_task(social_update_task())
        print("✅ Started social media tracking task")

    if not hasattr(bot, 'event_task'):
        bot.event_task = bot.loop.create_task(event_schedule_notifier())
        print("✅ Started tournament event schedule task")

@bot.event
async def on_guild_join(guild):
    """Handle joining new servers"""
    print(f"✅ Joined new server: {guild.name} (ID: {guild.id})")
    guild_id = str(guild.id)
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
        save_config()
    
    try:
        await bot.tree.sync(guild=guild)
        print(f"✅ Synced commands for {guild.name}")
    except Exception as e:
        print(f"❌ Failed to sync commands for {guild.name}: {e}")


@bot.event
async def on_guild_remove(guild):
    """Handle leaving servers"""
    print(f"❌ Left server: {guild.name} (ID: {guild.id})")
    guild_id = str(guild.id)
    if guild_id in guild_configs:
        del guild_configs[guild_id]
        save_config()
    if guild_id in social_trackers:
        del social_trackers[guild_id]
        save_social_trackers()


async def generate_welcome_card(member: discord.Member, banner_url: str):
    try:
        # Create blank image (800x400)
        width, height = 800, 400
        base = Image.new('RGB', (width, height), (40, 40, 40))
        
        # Download and paste banner
        async with aiohttp.ClientSession() as session:
            async with session.get(banner_url) as resp:
                if resp.status == 200:
                    banner_data = await resp.read()
                    banner = Image.open(io.BytesIO(banner_data)).convert('RGBA')
                    banner = banner.resize((width, 300))
                    base.paste(banner, (0, 0), banner)
        
        # Get and paste avatar (circular)
        avatar_url = str(member.display_avatar.with_format('png').with_size(256))
        async with session.get(avatar_url) as resp:
            if resp.status == 200:
                avatar_data = await resp.read()
                avatar = Image.open(io.BytesIO(avatar_data)).convert('RGBA')
                
                # Create circular mask
                mask = Image.new('L', (200, 200), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 200, 200), fill=255)
                
                avatar = avatar.resize((200, 200))
                base.paste(avatar, (300, 250), mask)
        
        # Add text
        draw = ImageDraw.Draw(base)
        try:
            font = ImageFont.truetype("arial.ttf", 30)
        except:
            font = ImageFont.load_default()
        
        draw.text((400, 320), f"Welcome {member.name}!", font=font, fill="white", anchor="mm")
        
        # Save to bytes
        img_bytes = io.BytesIO()
        base.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
        
    except Exception as e:
        print(f"Error creating welcome card: {e}")
        return None
    

@bot.event
async def on_message(message: discord.Message):
    # Existing auto-reply to DMs
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        embed = discord.Embed(
            title="📬 Nexus Esports Support",
            description=(
                "Thank you for your message!\n\n"
                "For official support, please contact:\n"
                "• **@acroneop** in our Official Server\n"
                "• Join: https://discord.gg/xPGJCWpMbM\n\n"
                "We'll assist you as soon as possible!"
            ),
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    # Team Registration Handler
    if message.guild and not message.author.bot:
        guild_id = str(message.guild.id)
        session = active_team_collections.get(guild_id)
        
        if session and message.channel.id == session["post_channel_id"]:
            try:
                # First add reaction to show bot is processing
                await message.add_reaction('⏳')
                
                # Parse team information
                content = [line.strip() for line in message.content.split('\n') if line.strip()]
                if len(content) < 2:
                    raise ValueError("Invalid format. Need both team name and members.")
                
                # Extract team name
                team_name_line = content[0]
                if not team_name_line.lower().startswith('team name:'):
                    raise ValueError("First line must start with 'Team Name:'")
                team_name = team_name_line.split(':', 1)[1].strip()
                if not team_name:
                    raise ValueError("Team name cannot be empty")
                
                # Extract members
                members_line = content[1]
                if not members_line.lower().startswith('members:'):
                    raise ValueError("Second line must start with 'Members:'")
                
                # Parse mentions and validate
                members = []
                for mention in message.mentions:
                    if mention != message.author and mention not in members:
                        members.append(mention)
                
                # Validate team size
                required_size = session["team_size"]
                if len(members) + 1 != required_size:  # +1 for author
                    raise ValueError(f"Team must have exactly {required_size} members (including yourself)")
                
                # Check if author is in members
                if message.author in members:
                    raise ValueError("Don't include yourself in members list")
                
                # Check for duplicate teams/players
                for team in session["registered_teams"]:
                    if team_name.lower() == team["name"].lower():
                        raise ValueError("Team name already taken")
                    if message.author.id in team["member_ids"]:
                        raise ValueError("You're already in another team")
                    for member in members:
                        if member.id in team["member_ids"]:
                            raise ValueError(f"{member.display_name} is already in another team")
                
                # Check slot availability
                if len(session["registered_teams"]) >= session["max_slots"]:
                    raise ValueError("Tournament is full")
                
                # Register the team
                team_data = {
                    "name": team_name,
                    "captain_id": message.author.id,
                    "member_ids": [m.id for m in [message.author] + members],
                    "registration_time": datetime.utcnow().isoformat()
                }
                session["registered_teams"].append(team_data)
                
                # Assign team role
                team_role = message.guild.get_role(session["team_role_id"])
                if team_role:
                    try:
                        await message.author.add_roles(team_role)
                        for member in members:
                            await member.add_roles(team_role)
                    except discord.Forbidden:
                        print(f"Missing permissions to assign role {team_role.name}")
                
                # Post in registered channel
                registered_channel = message.guild.get_channel(session["registered_channel_id"])
                if registered_channel:
                    member_mentions = ' '.join([f"<@{mid}>" for mid in team_data["member_ids"]])
                    embed = discord.Embed(
                        title=f"Team Registered: {team_name}",
                        description=(
                            f"**Captain:** <@{message.author.id}>\n"
                            f"**Members:** {member_mentions}\n"
                            f"**Slot:** {len(session['registered_teams'])}/{session['max_slots']}"
                        ),
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    await registered_channel.send(embed=embed)
                
                # Update reactions
                await message.remove_reaction('⏳', bot.user)
                await message.add_reaction('✅')
                
                # Check if tournament is full
                if len(session["registered_teams"]) >= session["max_slots"]:
                    embed = discord.Embed(
                        title="Listing Closed",
                        description=(
                            f"All {session['max_slots']} slots have been finalized!\n"
                            "Contact us if you are missed!."
                        ),
                        color=discord.Color.gold()
                    )
                    await message.channel.send(embed=embed)
                    
                    # Post final team list
                    final_embed = discord.Embed(
                        title=f"🏆 Final Teams for {session['tournament_name']}",
                        color=discord.Color.blurple()
                    )
                    
                    for i, team in enumerate(session["registered_teams"], 1):
                        members = ', '.join([f"<@{mid}>" for mid in team["member_ids"]])
                        final_embed.add_field(
                            name=f"{i}. {team['name']}",
                            value=f"👤 {members}",
                            inline=False
                        )
                    
                    await registered_channel.send(embed=final_embed)
                    del active_team_collections[guild_id]
                
            except ValueError as e:
                await message.remove_reaction('⏳', bot.user)
                await message.add_reaction('❌')
                error_msg = await message.channel.send(
                    f"{message.author.mention} ❌ Error: {str(e)}\n"
                    "Correct format:\n"
                    "```\n"
                    "Team Name: Your Team Name\n"
                    "Members: @member1 @member2 ...\n"
                    "```",
                    delete_after=10
                )
                await asyncio.sleep(5)
                await message.delete()
                await error_msg.delete()
                
            except Exception as e:
                print(f"Error processing team registration: {e}")
                await message.remove_reaction('⏳', bot.user)
                await message.add_reaction('❌')
                error_msg = await message.channel.send(
                    f"{message.author.mention} ❌ An error occurred. Please try again.",
                    delete_after=10
                )
                await asyncio.sleep(5)
                await message.delete()
                await error_msg.delete()
    
    await bot.process_commands(message)

# Background tasks
async def check_social_updates():
    """Check all social trackers for updates"""
    for guild_id, trackers in social_trackers.items():
        for tracker in trackers:
            try:
                if tracker['platform'] == 'youtube':
                    await check_youtube_update(guild_id, tracker)
                await asyncio.sleep(1)
            except Exception as e:
                print(f"⚠️ Error in social update: {e}")

async def social_update_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_social_updates()
        except Exception as e:
            print(f"⚠️ Social update error: {e}")
        await asyncio.sleep(300)

async def event_schedule_notifier():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            now = datetime.utcnow()
            for guild_id, events in event_schedule.items():
                updated = False
                for event in events:
                    if event.get("notified"):
                        continue
                    
                    event_time = datetime.fromisoformat(event["time"])
                    time_diff = (event_time - now).total_seconds()

                    if 0 <= time_diff <= 300:
                        channel = bot.get_channel(int(event["channel_id"]))
                        if not channel:
                            continue

                        role_mention = f"<@&{event['ping_role_id']}>" if event.get("ping_role_id") else ""

                        embed = discord.Embed(
                            title=f"🎮 {event['title']}",
                            description=event['description'],
                            color=discord.Color.orange(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="🕒 Starts At", value=f"<t:{int(event_time.timestamp())}:F>")
                        if event.get("image_url"):
                            embed.set_image(url=event["image_url"])
                        embed.set_footer(text="Tournament Reminder • Nexus Esports")

                        await channel.send(content=role_mention if role_mention else None, embed=embed)
                        event["notified"] = True
                        updated = True

                if updated:
                    save_event_schedule()

        except Exception as e:
            print(f"⚠️ Event notifier error: {e}")
        
        await asyncio.sleep(60)

async def check_youtube_update(guild_id, tracker):
    if not youtube_service:
        return

    try:
        # First get channel info
        request = youtube_service.channels().list(
            part='statistics,snippet',
            id=tracker['channel_id']
        )
        response = request.execute()

        if not response.get('items'):
            print(f"[YouTube] No channel found for ID: {tracker['channel_id']}")
            return

        channel_info = response['items'][0]
        stats = channel_info['statistics']
        snippet = channel_info['snippet']
        channel_name = snippet['title']
        
        # Update last check time
        tracker['last_check_time'] = datetime.utcnow().timestamp()
        
        # Handle subscriber count
        sub_count_raw = stats.get('subscriberCount')
        current_subs = tracker.get('last_count', 0)
        
        if sub_count_raw and sub_count_raw.isdigit():
            current_subs = int(sub_count_raw)
        
        # Subscriber milestone check
        last_subs = tracker.get('last_count', 0)
        if isinstance(last_subs, int) and current_subs > last_subs:
            tracker['last_count'] = current_subs
            channel = bot.get_channel(int(tracker['post_channel']))
            if channel:
                embed = discord.Embed(
                    title="🎉 YouTube Milestone Reached!",
                    description=(
                        f"**{channel_name}** just hit **{current_subs:,} subscribers**!\n"
                        f"`+{current_subs - last_subs:,}` since last update"
                    ),
                    color=discord.Color.red(),
                    url=tracker['url']
                )
                embed.set_thumbnail(url="https://i.imgur.com/krKzGz0.png")
                embed.set_footer(text="Nexus Esports Social Tracker")
                await channel.send(embed=embed)

        # Video upload detection (only notify for videos <24 hours old)
        video_request = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            order="date",
            maxResults=1,
            type="video"
        )
        video_response = video_request.execute()
        
        if video_response.get('items'):
            latest_video = video_response['items'][0]
            video_id = latest_video['id']['videoId']
            publish_time = latest_video['snippet']['publishedAt']
            video_time = datetime.fromisoformat(publish_time.replace('Z',''))
            
            # Only notify if video is <24 hours old and not previously notified
            if (datetime.utcnow() - video_time) < timedelta(hours=24) and tracker.get("last_video_id") != video_id:
                embed = discord.Embed(
                    title=f"📺 New YouTube Video: {latest_video['snippet']['title']}",
                    url=f"https://youtu.be/{video_id}",
                    description=f"A new video was uploaded on {tracker['account_name']}!",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=tracker['account_name'], inline=True)
                embed.add_field(name="Published", value=f"<t:{int(video_time.timestamp())}:R>", inline=True)
                embed.set_image(url=latest_video['snippet']['thumbnails']['high']['url'])
                
                channel = bot.get_channel(int(tracker['post_channel']))
                if channel:
                    await channel.send(embed=embed)
                
                tracker['last_video_id'] = video_id

        # Live stream detection with @everyone ping
        live_request = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            eventType="live",
            type="video",
            maxResults=1
        )
        live_response = live_request.execute()
        
        if live_response.get('items'):
            live_video = live_response['items'][0]
            live_video_id = live_video['id']['videoId']
            live_title = live_video['snippet']['title']
            live_thumb = live_video['snippet']['thumbnails']['high']['url']
            
            # Check if this is a new stream or we should re-notify (every 6 hours)
            last_live_notify = tracker.get('last_live_notify_time', 0)
            should_notify = (
                tracker.get('last_live_video_id') != live_video_id or 
                (datetime.utcnow().timestamp() - last_live_notify) > 21600  # 6 hours
            )
            
            if should_notify:
                embed = discord.Embed(
                    title=f"🔴 {tracker['account_name']} is LIVE!",
                    url=f"https://youtu.be/{live_video_id}",
                    description=f"{live_title}",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=tracker['account_name'], inline=True)
                embed.set_image(url=live_thumb)
                
                channel = bot.get_channel(int(tracker['post_channel']))
                if channel:
                    await channel.send(
                        content="@everyone",  # Ping everyone for live streams
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions(everyone=True)
                    )
                
                tracker['last_live_video_id'] = live_video_id
                tracker['last_live_notify_time'] = datetime.utcnow().timestamp()

        # Save updates
        tracker['last_update_time'] = datetime.utcnow().timestamp()
        save_social_trackers()

    except HttpError as e:
        if e.resp.status == 403:
            print(f"[YouTube] API quota exceeded for {tracker['account_name']}")
        else:
            print(f"[YouTube] API error: {e}")
    except Exception as e:
        print(f"[YouTube] Error checking {tracker['account_name']}: {e}")

# Load configs on startup
load_config()
load_social_trackers()
load_event_schedule()

# UI Components
class ChannelSelect(discord.ui.Select):
    def __init__(self, channels):
        options = [
            discord.SelectOption(label=channel.name, value=str(channel.id))
            for channel in channels if isinstance(channel, discord.TextChannel)
        ][:25]  # Discord allows max 25 options

        super().__init__(
            placeholder="Select a channel to send the event notification",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        view: TournamentEventView = self.view
        view.selected_channel_id = int(self.values[0])
        await interaction.response.send_modal(view.modal)

class TournamentEventModal(Modal, title="📅 Schedule Tournament Event"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.title_input = TextInput(label="Event Title", placeholder="e.g., Grand Finals")
        self.description_input = TextInput(label="Description", style=discord.TextStyle.paragraph, required=True)
        self.datetime_input = TextInput(label="Start Time (YYYY-MM-DD HH:MM IST)", placeholder="e.g., 2025-07-10 18:30", required=True)
        self.role_input = TextInput(label="Ping Role ID or @mention (optional)", required=False)
        self.image_input = TextInput(label="Image URL (optional)", required=False)

        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.datetime_input)
        self.add_item(self.role_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        from dateutil.parser import parse as parse_datetime

        try:
            event_time_ist = parse_datetime(self.datetime_input.value)
            event_time = event_time_ist - timedelta(hours=5, minutes=30)
            if event_time < datetime.utcnow():
                raise ValueError("Event time must be in the future.")

            role_id = None
            if self.role_input.value:
                if self.role_input.value.startswith("<@&"):
                    role_id = int(self.role_input.value[3:-1])
                else:
                    role_id = int(self.role_input.value.strip())

            channel = interaction.guild.get_channel(self.view.selected_channel_id)
            if not channel:
                raise ValueError("Channel not found.")

            guild_id = str(interaction.guild.id)
            if guild_id not in event_schedule:
                event_schedule[guild_id] = []

            event_schedule[guild_id].append({
                "title": self.title_input.value,
                "description": self.description_input.value,
                "time": event_time.isoformat(),
                "channel_id": channel.id,
                "ping_role_id": role_id,
                "image_url": self.image_input.value or None,
                "notified": False
            })
            save_event_schedule()

            embed = discord.Embed(
                title=f"✅ {self.title_input.value} Scheduled",
                description=self.description_input.value,
                color=discord.Color.green()
            )
            embed.add_field(name="📅 Start Time", value=f"<t:{int(event_time.timestamp())}:F>")
            embed.add_field(name="📢 Channel", value=channel.mention)
            if role_id:
                embed.add_field(name="👥 Ping Role", value=f"<@&{role_id}>")
            if self.image_input.value:
                embed.set_image(url=self.image_input.value)

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                embed=create_embed("❌ Error", str(e), color=discord.Color.red()),
                ephemeral=True
            )

class TournamentEventView(View):
    def __init__(self, channels):
        super().__init__(timeout=120)
        self.modal = TournamentEventModal(self)
        self.selected_channel_id = None
        self.add_item(ChannelSelect(channels))

class AnnouncementModal(Modal, title='Create Announcement'):
    message = TextInput(
        label='Announcement Content',
        style=discord.TextStyle.paragraph,
        placeholder='Enter your announcement here...',
        required=True
    )

    def __init__(self, channel: discord.TextChannel, ping_everyone: bool, ping_here: bool, attachment: Optional[discord.Attachment] = None):
        super().__init__()
        self.channel = channel
        self.ping_everyone = ping_everyone
        self.ping_here = ping_here
        self.attachment = attachment

    async def on_submit(self, interaction: discord.Interaction):
        formatted_message = f"```\n{self.message.value}\n```"
        embed = discord.Embed(
            description=formatted_message,
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        ping_str = ""
        if self.ping_everyone:
            ping_str += "@everyone "
        if self.ping_here:
            ping_str += "@here "
        
        try:
            files = []
            if self.attachment:
                file = await self.attachment.to_file()
                files.append(file)
            
            await self.channel.send(
                content=ping_str if ping_str else None, 
                embed=embed,
                files=files,
                allowed_mentions=discord.AllowedMentions(everyone=True) if (self.ping_everyone or self.ping_here) else None
            )
            
            await interaction.response.send_message(
                embed=create_embed(
                    title="✅ Announcement Sent",
                    description=f"Announcement posted in {self.channel.mention}!",
                    color=discord.Color.green()
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Announcement Failed",
                    description=f"Error: {e}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

class DMModal(Modal, title='Send Direct Message'):
    message = TextInput(
        label='Message Content',
        style=discord.TextStyle.paragraph,
        placeholder='Type your message here...',
        required=True
    )

    def __init__(self, user: discord.User, attachment: Optional[discord.Attachment] = None):
        super().__init__()
        self.user = user
        self.attachment = attachment

    async def on_submit(self, interaction: discord.Interaction):
        try:
            formatted_message = (
                f"**📩 Message from {interaction.guild.name}:**\n"
                f"```\n{self.message.value}\n```\n\n"
                "For any queries or further support, contact @acroneop in our Official Server:\n"
                "https://discord.gg/xPGJCWpMbM"
            )
            
            if self.attachment:
                formatted_message += "\n\n📎 *Attachment included*"
            
            embed = discord.Embed(
                description=formatted_message,
                color=discord.Color(0x3e0000),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
            
            files = []
            if self.attachment:
                file = await self.attachment.to_file()
                files.append(file)
                embed.set_image(url=f"attachment://{file.filename}")
            
            await self.user.send(embed=embed, files=files)
            
            confirm_message = f"Message sent to {self.user.mention}"
            if self.attachment:
                confirm_message += f" with attachment: {self.attachment.filename}"
            
            await interaction.response.send_message(
                embed=create_embed(
                    title="✅ DM Sent",
                    description=confirm_message,
                    color=discord.Color.green()
                ),
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Failed to Send DM",
                    description="This user has DMs disabled or blocked the bot.",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                embed=create_embed(
                    title="❌ Error",
                    description=f"An error occurred: {str(e)}",
                    color=discord.Color.red()
                ),
                ephemeral=True
            )

class WelcomeConfigModal(Modal, title='Configure Welcome'):
    dm_message = TextInput(
        label='Welcome DM Message',
        style=discord.TextStyle.paragraph,
        placeholder='Enter the welcome message for new members...',
        required=True
    )
    dm_attachment_url = TextInput(
        label='Welcome Image URL (optional)',
        placeholder='https://example.com/image.png',
        required=False
    )

    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        
        if guild_id not in guild_configs:
            guild_configs[guild_id] = {}
        
        guild_configs[guild_id]["welcome_channel"] = self.channel.id
        guild_configs[guild_id]["welcome_dm"] = self.dm_message.value
        if self.dm_attachment_url.value:
            guild_configs[guild_id]["dm_attachment_url"] = self.dm_attachment_url.value
        save_config()
        
        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Welcome System Configured",
                description=(
                    f"Welcome messages will be sent to {self.channel.mention}\n"
                    f"DM message set to: ```\n{self.dm_message.value}\n```"
                ),
                color=discord.Color.green()
            ),
            ephemeral=True
        )

# Command Groups
# Tournament Commands
@bot.tree.command(name="add-tournament-event", description="Open a form to schedule a tournament event")
async def add_tournament_event(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            embed=create_embed("❌ Permission Denied", "You need 'Manage Server' permission", discord.Color.red()),
            ephemeral=True
        )
        return

    channels = interaction.guild.text_channels
    await interaction.response.send_message(
        content="Select a channel to begin:",
        view=TournamentEventView(channels),
        ephemeral=True
    )

@bot.tree.command(name="list-tournament-events", description="List upcoming tournament events")
async def list_tournament_events(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    events = event_schedule.get(guild_id, [])

    if not events:
        return await interaction.response.send_message(
            embed=create_embed(
                title="📅 Tournament Schedule",
                description="No upcoming events found.",
                color=discord.Color.blue()
            ),
            ephemeral=True
        )

    embed = discord.Embed(
        title="📅 Upcoming Tournament Events",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow()
    )

    for i, event in enumerate(events, 1):
        event_time = datetime.fromisoformat(event["time"]) + timedelta(hours=5, minutes=30)
        ping_role = f"<@&{event['ping_role_id']}>" if event.get("ping_role_id") else "None"
        embed.add_field(
            name=f"{i}. {event['title']}",
            value=(
                f"📝 {event['description']}\n"
                f"📅 **Time:** <t:{int(event_time.timestamp())}:F>\n"
                f"📢 **Channel:** <#{event['channel_id']}>\n"
                f"👥 **Ping:** {ping_role}\n"
                f"🔔 **Notified:** {'✅' if event.get('notified') else '❌'}"
            ),
            inline=False
        )

    embed.set_footer(text="Nexus Esports | Scheduled Tournament Events")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove-tournament-event", description="Remove a scheduled tournament event")
@app_commands.describe(index="The number of the event from the list (e.g., 1, 2, 3...)")
async def remove_tournament_event(interaction: discord.Interaction, index: int):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission to delete tournament events.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )

    guild_id = str(interaction.guild.id)
    events = event_schedule.get(guild_id, [])

    if not events:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ No Events",
                description="There are no events to remove.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )

    if index < 1 or index > len(events):
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Invalid Index",
                description=f"Please enter a number between 1 and {len(events)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )

    removed = events.pop(index - 1)
    if events:
        event_schedule[guild_id] = events
    else:
        del event_schedule[guild_id]

    save_event_schedule()

    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Event Removed",
            description=f"Removed event: **{removed['title']}**",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# Announcement Commands
@bot.tree.command(name="announce-simple", description="Send a simple text announcement")
@app_commands.describe(
    channel="Channel to send announcement to",
    ping_everyone="Ping @everyone with this announcement",
    ping_here="Ping @here with this announcement"
)
async def announce_simple(interaction: discord.Interaction, 
                         channel: discord.TextChannel,
                         ping_everyone: bool = False,
                         ping_here: bool = False):
    if not has_announcement_permission(interaction):
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need announcement permissions!",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    await interaction.response.send_modal(
        AnnouncementModal(channel, ping_everyone, ping_here)
    )

@bot.tree.command(name="announce-attachment", description="Send announcement with text and attachment")
@app_commands.describe(
    channel="Channel to send announcement to",
    attachment="File to attach to the announcement",
    ping_everyone="Ping @everyone with this announcement",
    ping_here="Ping @here with this announcement"
)
async def announce_attachment(interaction: discord.Interaction, 
                             channel: discord.TextChannel, 
                             attachment: discord.Attachment,
                             ping_everyone: bool = False,
                             ping_here: bool = False):
    if not has_announcement_permission(interaction):
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need announcement permissions!",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    await interaction.response.send_modal(
        AnnouncementModal(channel, ping_everyone, ping_here, attachment)
    )

@bot.tree.command(name="announce-only-attachment", description="Send announcement with only an attachment")
@app_commands.describe(
    channel="Channel to send announcement to",
    attachment="File to attach to the announcement",
    ping_everyone="Ping @everyone with this announcement",
    ping_here="Ping @here with this announcement"
)
async def announce_only_attachment(interaction: discord.Interaction, 
                                   channel: discord.TextChannel, 
                                   attachment: discord.Attachment,
                                   ping_everyone: bool = False,
                                   ping_here: bool = False):
    if not has_announcement_permission(interaction):
        embed = create_embed(
            title="❌ Permission Denied",
            description="You need the Announcement role or 'Manage Messages' permission!",
            color=discord.Color(0x3e0000)
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    try:
        ping_str = ""
        if ping_everyone:
            ping_str += "@everyone "
        if ping_here:
            ping_str += "@here "
        
        file = await attachment.to_file()
        
        await channel.send(
            content=ping_str if ping_str else None, 
            file=file,
            allowed_mentions=discord.AllowedMentions(everyone=True) if (ping_everyone or ping_here) else None
        )
        
        embed = create_embed(
            title="✅ Announcement Sent",
            description=f"Attachment-only announcement sent to {channel.mention}!",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        embed = create_embed(
            title="❌ Announcement Failed",
            description=f"Error: {e}",
            color=discord.Color(0x3e0000)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

# DM Commands
@bot.tree.command(name="dm-user", description="Send a DM to a specific user (Mods only)")
@app_commands.describe(
    user="The user to DM",
    attachment="(Optional) File to attach"
)
async def dm_user(interaction: discord.Interaction, 
                 user: discord.User,
                 attachment: Optional[discord.Attachment] = None):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Messages' permission",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    await interaction.response.send_modal(DMModal(user, attachment))

@bot.tree.context_menu(name="DM Reply to User")
async def dm_reply_to_user(interaction: discord.Interaction, message: discord.Message):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Messages' permission",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    class ReplyModal(Modal, title='DM Reply to User'):
        reply_message = TextInput(
            label='Your reply',
            style=discord.TextStyle.paragraph,
            placeholder='Type your reply here...',
            required=True
        )
        
        async def on_submit(self, interaction: discord.Interaction):
            try:
                formatted_content = (
                    f"**📩 Reply from {interaction.guild.name} regarding your message:**\n"
                    f"```\n{message.content}\n```\n\n"
                    f"**Moderator's reply:**\n"
                    f"```\n{self.reply_message.value}\n```\n\n"
                    "For any queries or further support, contact @acroneop in our Official Server:\n"
                    "https://discord.gg/xPGJCWpMbM"
                )
                
                embed = discord.Embed(
                    description=formatted_content,
                    color=discord.Color(0x3e0000),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
                
                await message.author.send(embed=embed)
                
                await interaction.response.send_message(
                    embed=create_embed(
                        title="✅ Reply Sent",
                        description=f"Reply sent to {message.author.mention} via DM!",
                        color=discord.Color.green()
                    ),
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Failed to Send DM",
                        description="This user has DMs disabled or blocked the bot.",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Error",
                        description=f"An error occurred: {str(e)}",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
    
    await interaction.response.send_modal(ReplyModal())

# Welcome System Commands
@bot.tree.command(name="set-welcome", description="Configure welcome messages")
@app_commands.describe(
    welcome_channel="Channel for welcome messages",
    banner_url="URL of banner image",
    welcome_message="Custom welcome message (use {member} for mention)"
)
async def set_welcome(interaction: discord.Interaction,
                     welcome_channel: discord.TextChannel,
                     banner_url: str,
                     welcome_message: Optional[str] = None):
    guild_id = str(interaction.guild.id)
    
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
    
    guild_configs[guild_id].update({
        "welcome_channel": welcome_channel.id,
        "banner_url": banner_url,
        "welcome_message": welcome_message or DEFAULT_WELCOME_MESSAGE
    })
    
    save_config()
    
    # Test the welcome message
    embed = discord.Embed(
        description=f"```\n{welcome_message or DEFAULT_WELCOME_MESSAGE}\n```",
        color=discord.Color(0x3e0000)
    )
    embed.set_image(url=banner_url)
    
    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Welcome System Configured",
            description=f"Welcome messages will be sent to {welcome_channel.mention}",
            color=discord.Color.green()
        ),
        ephemeral=True
    )
    await welcome_channel.send(embed=embed)

@bot.event
async def on_member_join(member: discord.Member):
    guild_id = str(member.guild.id)
    
    if guild_id not in guild_configs:
        return

    welcome_channel_id = guild_configs[guild_id].get("welcome_channel")
    if not welcome_channel_id:
        return

    channel = member.guild.get_channel(int(welcome_channel_id))
    if not channel:
        return

    try:
        # Get banner URL from config or use default
        banner_url = guild_configs[guild_id].get("banner_url", DEFAULT_BANNER_URL)
        
        # Generate welcome card with avatar and banner
        welcome_image = await generate_welcome_card(member, banner_url)
        
        if welcome_image:
            # Create embed with welcome text
            welcome_text = guild_configs[guild_id].get("welcome_message", DEFAULT_WELCOME_MESSAGE)
            welcome_text = welcome_text.replace("{member}", member.mention)
            
            file = discord.File(welcome_image, filename="welcome.png")
            
            embed = discord.Embed(
                description=f"```\n{welcome_text}\n```",
                color=discord.Color(0x3e0000)
            )
            embed.set_image(url="attachment://welcome.png")
            
            await channel.send(file=file, embed=embed)
        else:
            # Fallback if image generation fails
            await channel.send(
                f"💕 Welcome {member.mention} to Nexus Esports! 💕\n\n"
                "First click on Nexus Esports above\n"
                "and select 'Show All Channels'"
            )
            
    except Exception as e:
        print(f"Error in welcome system: {e}")
        await channel.send(f"Welcome {member.mention} to the server!")

    # Send DM welcome
    try:
        welcome_dm = guild_configs[guild_id].get("welcome_dm")
        dm_attachment_url = guild_configs[guild_id].get("dm_attachment_url")
        
        if welcome_dm:
            embed = discord.Embed(
                description=welcome_dm,
                color=discord.Color(0x3e0000),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
            if dm_attachment_url:
                embed.set_image(url=dm_attachment_url)
            if member.guild.icon:
                embed.set_thumbnail(url=member.guild.icon.url)
            await member.send(embed=embed)
        else:
            dm_message = (
                "🔸Welcome to Nexus Esports!🔸\n\n"
                "Thank you for joining our gaming community! We're excited to have you on board.\n\n"
                "As mentioned in our welcome channel:\n"
                "1. Click \"Nexus Esports\" at the top of the server\n"
                "2. Select \"Show All Channels\" to access everything\n"
                "3. Explore our community spaces!\n\n"
                "Quick Start:\n"
                "• Read #rules for guidelines\n"
                "• Introduce yourself in #introductions\n"
                "• Check #announcements for news\n"
                "• Join tournaments in #events\n\n"
                "Need help? Contact @acroneop or our mod team anytime!\n\n"
                "We're glad you're here!💖 "
            )
            embed = discord.Embed(
                description=dm_message,
                color=discord.Color(0x3e0000),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
            if member.guild.icon:
                embed.set_thumbnail(url=member.guild.icon.url)
            await member.send(embed=embed)
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"⚠️ Error sending welcome DM: {e}")

# Social Media Tracking Commands
@bot.tree.command(name="add-social-tracker", description="Add social media account tracking")
@app_commands.describe(
    platform="Select platform to track",
    account_url="Full URL to the account",
    post_channel="Channel to post updates"
)
@app_commands.choices(platform=[
    app_commands.Choice(name="YouTube", value="youtube")
])
async def add_social_tracker(interaction: discord.Interaction, 
                            platform: str, 
                            account_url: str,
                            post_channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission to set up trackers",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    guild_id = str(interaction.guild.id)
    
    if guild_id not in social_trackers:
        social_trackers[guild_id] = []
    
    account_info = {}
    try:
        if platform == "youtube":
            if not YOUTUBE_API_KEY:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ YouTube Disabled",
                        description="YouTube API key not configured",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            channel_id = None
        
            if "youtube.com/channel/" in account_url:
                channel_id = account_url.split("youtube.com/channel/")[1].split("/")[0].split("?")[0]
            elif "youtube.com/@" in account_url:
                handle = account_url.split("youtube.com/@")[1].split("/")[0].split("?")[0]
                
                request = youtube_service.channels().list(
                    part="id,snippet",
                    forUsername=handle
                )
                response = request.execute()
                
                if not response.get('items'):
                    return await interaction.response.send_message(
                        embed=create_embed(
                            title="❌ Channel Not Found",
                            description="Couldn't find YouTube channel with that handle",
                            color=discord.Color.red()
                        ),
                        ephemeral=True
                    )
                    
                channel_id = response['items'][0]['id']
            else:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Invalid URL",
                        description="Please provide a valid YouTube channel URL",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
        
            search_req = youtube_service.search().list(
                part="id",
                channelId=channel_id,
                order="date",
                maxResults=1,
                type="video"
            )
            search_res = search_req.execute()
            latest_video_id = search_res['items'][0]['id']['videoId'] if search_res.get('items') else None
        
            search_live = youtube_service.search().list(
                part="id",
                channelId=channel_id,
                eventType="live",
                type="video",
                maxResults=1
            ).execute()
            latest_live_id = search_live['items'][0]['id']['videoId'] if search_live.get('items') else None
        
            request = youtube_service.channels().list(
                part='statistics,snippet',
                id=channel_id
            )
            response = request.execute()
            
            if not response.get('items'):
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Channel Not Found",
                        description="Couldn't find YouTube channel",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            stats = response['items'][0]['statistics']
            account_info = {
                'platform': platform,
                'url': account_url,
                'channel_id': channel_id,
                'account_name': response['items'][0]['snippet']['title'],
                'last_count': int(stats['subscriberCount']),
                'last_video_id': latest_video_id,
                'last_live_video_id': latest_live_id,
                'post_channel': str(post_channel.id)
            }

    except HttpError as e:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ YouTube API Error",
                description=f"YouTube API error: {str(e)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    except Exception as e:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Setup Failed",
                description=f"Error: {str(e)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    social_trackers[guild_id].append(account_info)
    save_social_trackers()
    
    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Tracker Added",
            description=(
                f"Now tracking **{account_info['account_name']}** on {platform.capitalize()}!\n"
                f"Updates will be posted in {post_channel.mention}"
            ),
            color=discord.Color.green()
        ),
        ephemeral=True
    )

@bot.tree.command(name="list-social-trackers", description="Show active social media trackers")
async def list_social_trackers(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    guild_id = str(interaction.guild.id)
    trackers = social_trackers.get(guild_id, [])
    
    # Debug output to verify loaded data
    print(f"[DEBUG] Trackers for {guild_id}: {json.dumps(trackers, indent=2)}")
    
    if not trackers:
        return await interaction.response.send_message(
            embed=create_embed(
                title="📊 Social Trackers",
                description="No active trackers configured",
                color=discord.Color.blue()
            ),
            ephemeral=True
        )
    
    embed = discord.Embed(
        title="📊 Active Social Trackers",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    for i, tracker in enumerate(trackers, 1):
        try:
            channel_id = tracker.get('post_channel')
            channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
            
            count = tracker.get('last_count', 'N/A')
            if isinstance(count, int):
                count = f"{count:,}"
                
            # Handle channel display
            channel_display = channel.mention if channel else f"⚠️ Channel not found (ID: {channel_id})"
            
            # Add last update time if available
            last_update = ""
            if 'last_update_time' in tracker:
                last_update = f"\n**Last Update:** <t:{int(tracker['last_update_time'])}:R>"
            
            embed.add_field(
                name=f"{i}. {tracker['account_name']}",
                value=(
                    f"**Platform:** {tracker['platform'].capitalize()}\n"
                    f"**Channel:** {channel_display}\n"
                    f"**Current Count:** {count}"
                    f"{last_update}\n"
                    f"[View Profile]({tracker['url']})"
                ),
                inline=False
            )
        except Exception as e:
            print(f"Error processing tracker {i}: {e}")
            continue
    
    embed.set_footer(text="Nexus Esports Social Tracker")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove-social-tracker", description="Remove a social media tracker")
@app_commands.describe(index="Tracker number to remove (see /list-social-trackers)")
async def remove_social_tracker(interaction: discord.Interaction, index: int):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    guild_id = str(interaction.guild.id)
    trackers = social_trackers.get(guild_id, [])
    
    if index < 1 or index > len(trackers):
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Invalid Index",
                description="Please use a valid tracker number",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    removed = trackers.pop(index-1)
    if trackers:
        social_trackers[guild_id] = trackers
    else:
        del social_trackers[guild_id]
    save_social_trackers()
    
    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Tracker Removed",
            description=f"No longer tracking **{removed['account_name']}**",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# Team Registration Commands
@bot.tree.command(name="collect-teams", description="Start team registration for a tournament")
@app_commands.describe(
    team_size="Number of members per team",
    tournament_name="Name of the tournament",
    post_channel="Channel to post the registration message",
    registered_channel="Channel to post registered teams",
    team_role="Role to assign to team members",
    max_slots="Maximum number of teams allowed to register"
)
async def collect_teams(
    interaction: discord.Interaction,
    team_size: int,
    tournament_name: str,
    post_channel: discord.TextChannel,
    registered_channel: discord.TextChannel,
    team_role: discord.Role,
    max_slots: int
):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission to use this command.",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)
    active_team_collections[guild_id] = {
        "team_size": team_size,
        "tournament_name": tournament_name,
        "post_channel_id": post_channel.id,
        "registered_channel_id": registered_channel.id,
        "team_role_id": team_role.id,
        "creator_id": interaction.user.id,
        "max_slots": max_slots,
        "registered_teams": []
    }

    instructions = (
        f"**Please provide your team information for `{tournament_name}`!**\n\n"
        f"Reply in this channel with:\n"
        f"`Team Name: <your team name>`\n"
        f"`Members: @member1 @member2 ... (mention {team_size} members including yourself)`\n\n"
        f"Example:\n"
        f"Team Name: Raze Nexus\n"
        f"Members: @user1 @user2 @user3\n\n"
        f"**Each team must have exactly {team_size} members.**\n"
        f"**Maximum slots:** {max_slots}"
    )
    
    embed = discord.Embed(
        title=f"🏆 {tournament_name} Registered Teams",
        description=instructions,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.set_footer(text="Nexus Esports | Registered Teams")
    await post_channel.send(embed=embed)
    await interaction.response.send_message(
        embed=create_embed(
            title="Collecting TEAMS as per your preferences!",
            description=f"posted in {post_channel.mention}. Teams will be posted in {registered_channel.mention}.",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# Utility Commands
@bot.tree.command(name="add-link", description="Add link professionally")
@app_commands.describe(
    url="The URL to add (must start with http:// or https://)",
    title="(Optional) Title for the link",
    description="(Optional) Description text"
)
async def add_link(interaction: discord.Interaction, 
                  url: str, 
                  title: Optional[str] = None,
                  description: Optional[str] = None):
    if not url.startswith(("http://", "https://")):
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Invalid URL",
                description="URL must start with http:// or https://",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    try:
        link_text = f"[Click Here to visit]({url})"
        embed_description = f"**➤ {link_text}**"
        if description:
            embed_description += f"\n\n{description}"
        
        embed = create_embed(
            title=title if title else "Link here",
            description=embed_description,
            color=discord.Color(0x3e0000)
        )
        embed.url = url
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Error Creating Link",
                description=f"An error occurred: {str(e)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )

@bot.tree.command(name="reply-in-channel", description="Reply to a user in this channel (Mods only)")
@app_commands.describe(
    user="The user you're replying to",
    message="Your reply message content",
    message_id="(Optional) ID of the specific message to reply to"
)
async def reply_in_channel(interaction: discord.Interaction, 
                         user: discord.Member,
                         message: str,
                         message_id: Optional[str] = None):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Messages' permission to use this command",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
    
    try:
        arrow = "↳"
        formatted_content = (
            f"{arrow} **Replying to {user.mention}**\n\n"
            f"```\n{message}\n```"
        )
        
        embed = discord.Embed(
            description=formatted_content,
            color=discord.Color(0x3e0000),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        reference = None
        if message_id:
            try:
                message_id_int = int(message_id)
                ref_message = await interaction.channel.fetch_message(message_id_int)
                reference = ref_message.to_reference(fail_if_not_exists=False)
            except (ValueError, discord.NotFound, discord.HTTPException):
                pass
        
        await interaction.channel.send(
            embed=embed,
            reference=reference
        )
        
        await interaction.response.send_message(
            embed=create_embed(
                title="✅ Reply Sent",
                description=f"Replied to {user.mention} in {interaction.channel.mention}",
                color=discord.Color.green()
            ),
            ephemeral=True
        )
        
    except Exception as e:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Reply Failed",
                description=f"Error: {str(e)}",
                color=discord.Color.red()
            ),
            ephemeral=True
        )

@bot.tree.command(name="set-announce-role", description="Set announcement role for this server (Admin only)")
@app_commands.describe(role="Role to use for announcement permissions")
async def set_announce_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.manage_guild:
        embed = create_embed(
            title="❌ Permission Denied",
            description="You need 'Manage Server' permission to set announcement roles.",
            color=discord.Color(0x3e0000)
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    guild_id = str(interaction.guild.id)
    
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
    
    guild_configs[guild_id]["announcement_role"] = role.id
    save_config()
    
    embed = create_embed(
        title="✅ Announcement Role Set",
        description=f"{role.mention} is now the announcement role for this server.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="sync-commands", description="Sync bot commands (Server Owner only)")
async def sync_commands(interaction: discord.Interaction):
    app_info = await bot.application_info()
    is_bot_owner = interaction.user.id == app_info.owner.id
    is_server_owner = interaction.guild and interaction.user.id == interaction.guild.owner_id
    
    if not (is_bot_owner or is_server_owner):
        embed = create_embed(
            title="❌ Permission Denied",
            description="Only server owners or bot owners can sync commands.",
            color=discord.Color(0x3e0000)
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    invite_url = discord.utils.oauth_url(
        bot.user.id,
        permissions=discord.Permissions(
            send_messages=True,
            embed_links=True,
            view_channel=True,
            read_message_history=True,
            mention_everyone=True,
            manage_messages=True,
            attach_files=True
        ),
        scopes=("bot", "applications.commands")
    )
    
    try:
        if interaction.guild:
            await bot.tree.sync(guild=interaction.guild)
            message = f"✅ Commands synced for {interaction.guild.name}!"
        else:
            await bot.tree.sync()
            message = "✅ Global commands synced!"
        
        embed = create_embed(
            title="✅ Sync Successful",
            description=message,
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.Forbidden as e:
        description = (
            f"❌ **Sync Failed: Bot lacks permissions**\n"
            f"Error: `{e}`\n\n"
            "**Troubleshooting Steps:**\n"
            "1. Re-invite the bot using this link with proper permissions:\n"
            f"{invite_url}\n"
            "2. Ensure the bot has **Manage Server** permission\n"
            "3. Server owner must run this command\n"
            "4. Check bot has `applications.commands` scope\n"
            "5. Wait 1 hour after bot invite for permissions to propagate"
        )
        embed = create_embed(
            title="❌ Sync Failed - Permissions Issue",
            description=description,
            color=discord.Color(0x3e0000)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        description = (
            f"❌ **Sync Failed**\n"
            f"Error: `{e}`\n\n"
            "**Troubleshooting Steps:**\n"
            "1. Ensure the bot has `applications.commands` scope in invite\n"
            "2. Re-invite the bot using this link:\n"
            f"{invite_url}\n"
            "3. Server owner must run this command\n"
            "4. Try again in 5 minutes (Discord API might be slow)\n"
            "5. Contact support if issue persists"
        )
        embed = create_embed(
            title="❌ Sync Failed",
            description=description,
            color=discord.Color(0x3e0000)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="force-sync", description="Force resync all commands")
async def force_sync(interaction: discord.Interaction):
    try:
        await bot.tree.sync()
        await interaction.response.send_message("✅ Slash commands globally resynced.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

# Bot startup
async def main():
    try:
        await bot.load_extension("scrim")
        print("✅ Scrim commands loaded.")
    except Exception as e:
        print(f"⚠️ Could not load scrim extension: {e}")
    
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user.")
        sys.exit(0)
