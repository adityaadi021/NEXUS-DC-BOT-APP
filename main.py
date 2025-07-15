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
    # Prioritize live stream checks, then other updates, and batch API calls for quota efficiency
    youtube_trackers = []
    for guild_id, trackers in social_trackers.items():
        for tracker in trackers:
            if tracker['platform'] == 'youtube':
                youtube_trackers.append((guild_id, tracker))

    # Group by channel_id to avoid duplicate API calls
    channel_map = {}
    for guild_id, tracker in youtube_trackers:
        cid = tracker['channel_id']
        if cid not in channel_map:
            channel_map[cid] = []
        channel_map[cid].append((guild_id, tracker))

    # 1. Check live streams for all channels first (priority)
    for channel_id, tracker_list in channel_map.items():
        try:
            # Only one API call per channel for live
            live_request = youtube_service.search().list(
                part="snippet",
                channelId=channel_id,
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
                for guild_id, tracker in tracker_list:
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
                                embed=embed,
                                allowed_mentions=discord.AllowedMentions(everyone=True)
                current_subs = tracker.get('last_count', 0)
                if sub_count_raw and sub_count_raw.isdigit():
    channel = member.guild.get_channel(int(welcome_channel_id))
    if not channel:
        return
    try:
        # Get banner URL from config or use default
        banner_url = guild_configs[guild_id].get("banner_url", DEFAULT_BANNER_URL)
        # Get welcome text from config or use default
        welcome_text = guild_configs[guild_id].get("welcome_message", DEFAULT_WELCOME_MESSAGE)
        # Generate custom welcome image (username above member count)
        from PIL import Image, ImageDraw, ImageFont
        import io
        avatar_asset = member.display_avatar.replace(format="png", size=128)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        width, height = 800, 300
        bg = Image.new("RGBA", (width, height), (24, 24, 32, 255))
        draw = ImageDraw.Draw(bg)
        avatar_size = 128
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = avatar_img.resize((avatar_size, avatar_size))
        bg.paste(avatar_img, ((width-avatar_size)//2, 40), mask)
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        username = str(member.display_name)
        user_w, user_h = draw.textsize(username, font=font)
        draw.text(((width-user_w)//2, 40+avatar_size+10), username, font=font, fill=(255,255,255,255))
        msg = f"You are our {member.guild.member_count}th member!"
        msg_w, msg_h = draw.textsize(msg, font=font)
        draw.text(((width-msg_w)//2, 40+avatar_size+10+user_h+10), msg, font=font, fill=(255,255,255,255))
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="welcome.png")

        # First embed: custom image and welcome text
        embed1 = discord.Embed(
            description=f"Hey {member.mention}!\n\n```
                    video_time = datetime.fromisoformat(publish_time.replace('Z',''))
                    if (datetime.utcnow() - video_time) < timedelta(hours=12) and tracker.get("last_video_id") != video_id:
            color=discord.Color(0x3e0000)
        )
        embed1.set_image(url="attachment://welcome.png")
        # Second embed: banner GIF
        embed2 = discord.Embed()
        embed2.set_image(url=banner_url)
        await channel.send(embeds=[embed1, embed2], file=file)

        # Send DM welcome
        try:
            welcome_dm = guild_configs[guild_id].get("welcome_dm")
            dm_attachment_url = guild_configs[guild_id].get("dm_attachment_url")
            if welcome_dm:
                embed = discord.Embed(
                    description=f"Hey {member.mention}!\n{welcome_dm}",
                    color=discord.Color(0x3e0000)
                )
                if dm_attachment_url:
                    embed.set_image(url=dm_attachment_url)
                await member.send(embed=embed)
        except Exception as e:
            print(f"Error sending welcome DM: {e}")
    except Exception as e:
        print(f"Error in on_member_join: {e}")
                        embed = discord.Embed(
                            title=f"📺 New YouTube upload: {latest_video['snippet']['title']}",
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

                tracker['last_update_time'] = datetime.utcnow().timestamp()
                save_social_trackers()
        except HttpError as e:
            if e.resp.status == 403:
                print(f"[YouTube] API quota exceeded for channel {channel_id}")
            else:
                print(f"[YouTube] API error: {e}")
        except Exception as e:
            print(f"[YouTube] Error checking channel {channel_id}: {e}")

async def social_update_task():
    await bot.wait_until_ready()
    # Run every 2 minutes for near-minimum delay, but quota-friendly
    while not bot.is_closed():
        try:
            await check_social_updates()
        except Exception as e:
            print(f"⚠️ Social update error: {e}")
        await asyncio.sleep(120)

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
    # Deprecated: now handled in batch in check_social_updates for quota efficiency
    pass

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

    try:
        # Get banner URL from config or use default
        banner_url = guild_configs[guild_id].get("banner_url", DEFAULT_BANNER_URL)
        # Get welcome text from config or use default
        welcome_text = guild_configs[guild_id].get("welcome_message", DEFAULT_WELCOME_MESSAGE)

        # Try to generate a custom welcome image
        import io
        from PIL import Image, ImageDraw, ImageFont
        avatar_asset = member.display_avatar.replace(format="png", size=128)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

        # Create dark background
        width, height = 800, 300
        bg = Image.new("RGBA", (width, height), (24, 24, 32, 255))
        draw = ImageDraw.Draw(bg)

        # Paste avatar in center (circle)
        avatar_size = 128
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = avatar_img.resize((avatar_size, avatar_size))
        bg.paste(avatar_img, ((width-avatar_size)//2, 40), mask)

        # Write custom message below avatar
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except:
            font = ImageFont.load_default()
        msg = f"You are our {member.guild.member_count}th member!"
        text_w, text_h = draw.textsize(msg, font=font)
        draw.text(((width-text_w)//2, 40+avatar_size+20), msg, font=font, fill=(255,255,255,255))

        # Save to buffer
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="welcome.png")

        # Embed with image and welcome text
        embed = discord.Embed(
            description=f"Hey {member.mention}!\n\n```\n{welcome_text}\n```"
        )
        embed.set_image(url="attachment://welcome.png")
        await channel.send(embed=embed, file=file)

    except Exception as e:
        print(f"Error in welcome system: {e}")
        # Fallback to current embed with banner
        embed = discord.Embed(
            description=f"Hey {member.mention}!\n\n```\n{welcome_text}\n```"
        )
        embed.set_image(url=banner_url)
        await channel.send(embed=embed)
    # The following code was orphaned and is removed for clarity and correctness.

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

    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Welcome System Configured",
            description=f"Welcome messages will be sent to {welcome_channel.mention}\n\nAn example welcome message will be sent below.",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

    # Send example welcome message in the selected channel
    member = interaction.user
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        avatar_asset = member.display_avatar.replace(format="png", size=128)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        width, height = 800, 300
        bg = Image.new("RGBA", (width, height), (24, 24, 32, 255))
        draw = ImageDraw.Draw(bg)
        avatar_size = 128
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = avatar_img.resize((avatar_size, avatar_size))
        bg.paste(avatar_img, ((width-avatar_size)//2, 40), mask)
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        username = str(member.display_name)
        user_w, user_h = draw.textsize(username, font=font)
        draw.text(((width-user_w)//2, 40+avatar_size+10), username, font=font, fill=(255,255,255,255))
        msg = f"You are our {welcome_channel.guild.member_count}th member!"
        msg_w, msg_h = draw.textsize(msg, font=font)
        draw.text(((width-msg_w)//2, 40+avatar_size+10+user_h+10), msg, font=font, fill=(255,255,255,255))
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="welcome.png")
        embed1 = discord.Embed(
            description=(
                f"Hey {member.mention}!\n\n"
                f"```\n{welcome_message or DEFAULT_WELCOME_MESSAGE}\n```"
            ),
            color=discord.Color(0x3e0000)
        )
        embed1.set_image(url="attachment://welcome.png")
        embed2 = discord.Embed()
        embed2.set_image(url=banner_url or DEFAULT_BANNER_URL)
        await welcome_channel.send(embeds=[embed1, embed2], file=file)
    except Exception as e:
        await welcome_channel.send(f"Failed to send example welcome message: {e}")

@bot.event
async def on_member_join(member: discord.Member):
    guild_id = str(member.guild.id)
    
    if guild_id not in guild_configs:
        return

    welcome_channel_id = guild_configs[guild_id].get("welcome_channel")
    if not welcome_channel_id:
        return

    channel = member.guild.get_channel(int(welcome_channel_id))
        embed1 = discord.Embed(
            description=f"Hey {member.mention}!\n\n```
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
        # Get welcome text from config or use default
        welcome_text = guild_configs[guild_id].get("welcome_message", DEFAULT_WELCOME_MESSAGE)
        # Generate custom welcome image (username above member count)
        from PIL import Image, ImageDraw, ImageFont
        import io
        avatar_asset = member.display_avatar.replace(format="png", size=128)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        width, height = 800, 300
        bg = Image.new("RGBA", (width, height), (24, 24, 32, 255))
        draw = ImageDraw.Draw(bg)
        avatar_size = 128
        mask = Image.new("L", (avatar_size, avatar_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
        avatar_img = avatar_img.resize((avatar_size, avatar_size))
        bg.paste(avatar_img, ((width-avatar_size)//2, 40), mask)
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except Exception:
            font = ImageFont.load_default()
        username = str(member.display_name)
        user_w, user_h = draw.textsize(username, font=font)
        draw.text(((width-user_w)//2, 40+avatar_size+10), username, font=font, fill=(255,255,255,255))
        msg = f"You are our {member.guild.member_count}th member!"
        msg_w, msg_h = draw.textsize(msg, font=font)
        draw.text(((width-msg_w)//2, 40+avatar_size+10+user_h+10), msg, font=font, fill=(255,255,255,255))
        buf = io.BytesIO()
        bg.save(buf, format="PNG")
        buf.seek(0)
        file = discord.File(buf, filename="welcome.png")

        # First embed: custom image and welcome text
        embed1 = discord.Embed(
            description=f"Hey {member.mention}!\n\n```
        # Second embed: banner GIF
        )
        embed1.set_image(url="attachment://welcome.png")
        embed1 = discord.Embed(
            description=f"Hey {member.mention}!\n\n```
        embed2.set_image(url=banner_url)
            color=discord.Color(0x3e0000)
        )
        await channel.send(embeds=[embed1, embed2], file=file)

        # Send DM welcome
        try:
            welcome_dm = guild_configs[guild_id].get("welcome_dm")
            dm_attachment_url = guild_configs[guild_id].get("dm_attachment_url")
            if welcome_dm:
                embed = discord.Embed(
                    description=f"Hey {member.mention}!\n{welcome_dm}",
                    color=discord.Color(0x3e0000)
                )
                if dm_attachment_url:
                    embed.set_image(url=dm_attachment_url)
                await member.send(embed=embed)
        except Exception as e:
            print(f"Error sending welcome DM: {e}")
    except Exception as e:
        print(f"Error in on_member_join: {e}")
        embed2.set_image(url=banner_url)
        await channel.send(embeds=[embed1, embed2], file=file)

        # Send DM welcome
        try:
            welcome_dm = guild_configs[guild_id].get("welcome_dm")
            dm_attachment_url = guild_configs[guild_id].get("dm_attachment_url")
            if welcome_dm:
                embed = discord.Embed(
                    description=f"Hey {member.mention}!\n{welcome_dm}",
                    color=discord.Color(0x3e0000)
                )
                if dm_attachment_url:
                    embed.set_image(url=dm_attachment_url)
                await member.send(embed=embed)
        except Exception as e:
            print(f"Error sending welcome DM: {e}")
    except Exception as e:
        print(f"Error in on_member_join: {e}")
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
