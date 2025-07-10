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
import scrim  # Ensure scrim is imported

# Add PIL import for image generation
from PIL import Image, ImageDraw, ImageFont
import io


print("🚀 Bot is starting...")

app = Flask(__name__)

# Flask route handlers
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

# Add this near your other initialization code (around line 20)
AVATAR_FILE = "bot_avatar.gif"  # or .gif for animated
BANNER_FILE = "bot_banner.png"

async def set_bot_assets_on_startup():
    """Automatically set bot avatar and banner on startup if files exist"""
    try:
        # Set Avatar (supports PNG/JPEG/GIF)
        if os.path.exists(AVATAR_FILE):
            with open(AVAR_FILE, "rb") as f:
                await bot.user.edit(avatar=f.read())
            print("✅ Bot avatar set automatically!")
        
        # Set Banner (requires PNG/JPEG)
        if os.path.exists(BANNER_FILE):
            with open(BANNER_FILE, "rb") as f:
                await bot.user.edit(banner=f.read())
            print("✅ Bot banner set automatically!")
    except Exception as e:
        print(f"⚠️ Failed to set bot assets on startup: {e}")

# Modify your existing on_ready() event (around line 220)
@bot.event
async def on_ready():
    global commands_synced
    print(f"✅ Bot ready! Logged in as {bot.user}")
    
    # Print invite link with proper scopes
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
        status=discord.Status.online,  # Can be online, idle, dnd, invisible
        activity=discord.Game('Watching')  # You can use Game, Streaming, Listening, Watching
    )
    
    # Auto-set bot assets
    await set_bot_assets_on_startup()
    
    if not commands_synced:
        try:
            synced = await bot.tree.sync()
            commands_synced = True
            print(f"✅ Synced {len(synced)} command(s) globally")
        except Exception as e:
            print(f"❌ Command sync failed: {e}")
    
    # Start background tasks
    if not hasattr(bot, 'social_task'):
        bot.social_task = bot.loop.create_task(social_update_task())
        print("✅ Started social media tracking task")

    if not hasattr(bot, 'event_task'):
        bot.event_task = bot.loop.create_task(event_schedule_notifier())
        print("✅ Started tournament event schedule task")

        
# --- SCRIM COMMANDS LOADING ---
# Add this after bot definition and before on_ready
# If scrim.py is a cog, use:
try:
    bot.load_extension("scrim")
    print("✅ Scrim commands loaded.")
except Exception as e:
    print(f"⚠️ Could not load scrim extension: {e}")

# Load configs on startup
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
    """Remove a tournament event by index"""
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

@bot.tree.command(name="force-sync", description="Force resync all commands")
async def force_sync(interaction: discord.Interaction):
    try:
        await bot.tree.sync()
        await interaction.response.send_message("✅ Slash commands globally resynced.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

# Tournament Event Schedule
# Remove the duplicate on_ready event (keep only one, merge logic)
# Keep only ONE on_ready event, merge asset setup and background tasks
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

    # Auto-set bot assets
    await set_bot_assets_on_startup()

    if not commands_synced:
        try:
            synced = await bot.tree.sync()
            commands_synced = True
            print(f"✅ Synced {len(synced)} command(s) globally")
        except Exception as e:
            print(f"❌ Command sync failed: {e}")

    # Start background tasks
    if not hasattr(bot, 'social_task'):
        bot.social_task = bot.loop.create_task(social_update_task())
        print("✅ Started social media tracking task")

    if not hasattr(bot, 'event_task'):
        bot.event_task = bot.loop.create_task(event_schedule_notifier())
        print("✅ Started tournament event schedule task")


# Load configs on startup
load_config()
load_social_trackers()
load_event_schedule()

# Background task for social updates

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
        await asyncio.sleep(300)  # Check every 5 minutes

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

                    if 0 <= time_diff <= 300:  # 5 minutes
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
        
        await asyncio.sleep(60)  # check every 60 seconds

async def check_youtube_update(guild_id, tracker):
    if not youtube_service:
        return

    try:
        # Get current channel stats
        request = youtube_service.channels().list(
            part='statistics,snippet',
            id=tracker['channel_id']
        )
        response = request.execute()

        if not response.get('items'):
            return

        stats = response['items'][0]['statistics']
        snippet = response['items'][0]['snippet']
        channel_name = snippet['title']
        
        # Get subscriber count
        sub_count_raw = stats.get('subscriberCount')
        
        # Handle hidden subscriber counts - don't exit, just use previous value
        if not sub_count_raw or not sub_count_raw.isdigit():
            print(f"⚠️ Hidden subscriber count for {tracker['account_name']}")
            current_subs = tracker.get('last_count', 0)
        else:
            current_subs = int(sub_count_raw)

        last_subs = tracker.get('last_count', 0)

        # Auto-fix corrupted or missing count
        if not isinstance(last_subs, int) or last_subs == 0:
            tracker['last_count'] = current_subs
            save_social_trackers()

        # If subscriber growth, send milestone alert
        elif current_subs > last_subs:
            tracker['last_count'] = current_subs
            save_social_trackers()

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

        # FIX 2: Add null check for video detection
        # Detect new video uploads
        upload_req = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            order="date",
            maxResults=1,
            type="video"
        )
        upload_res = upload_req.execute()
        if upload_res.get('items'):
            latest_video = upload_res['items'][0]
            video_id = latest_video['id']['videoId']
            video_title = latest_video['snippet']['title']
            publish_time = latest_video['snippet']['publishedAt']

            # Only notify if video_id exists and is different
            if video_id and tracker.get("last_video_id") != video_id:
                embed = discord.Embed(
                    title=f"📺 New YouTube Video: {video_title}",
                    url=f"https://youtu.be/{video_id}",
                    description=f"A new video was uploaded on {tracker['account_name']}!",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=tracker['account_name'], inline=True)
                embed.add_field(name="Published", value=f"<t:{int(datetime.fromisoformat(publish_time.replace('Z','')).timestamp())}:R>", inline=True)
                # Move thumbnail to bottom and make it bigger
                embed.set_image(url=latest_video['snippet']['thumbnails']['high']['url'])
                # Remove set_thumbnail if present
                # Send notification
                channel = bot.get_channel(int(tracker['post_channel']))
                if channel:
                    await channel.send(embed=embed)
                tracker['last_video_id'] = video_id
                save_social_trackers()

        # FIX 3: Add null check for live detection
        # Detect if channel is live
        live_req = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            eventType="live",
            type="video",
            maxResults=1
        )
        live_res = live_req.execute()
        if live_res.get('items'):
            live_video = live_res['items'][0]
            live_video_id = live_video['id']['videoId']
            live_title = live_video['snippet']['title']
            live_thumb = live_video['snippet']['thumbnails']['high']['url']

            # --- Improved notification logic ---
            now = datetime.utcnow().timestamp()
            cooldown = 30 * 60  # 30 minutes in seconds
            last_notified = tracker.get('last_live_notified', 0)
            last_live_id = tracker.get('last_live_video_id')

            should_notify = False
            if live_video_id != last_live_id:
                # New live stream detected
                should_notify = True
            elif now - last_notified > cooldown:
                # Same stream, but cooldown passed
                should_notify = True

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
                    await channel.send(embed=embed)
                tracker['last_live_video_id'] = live_video_id
                tracker['last_live_notified'] = now
                save_social_trackers()

    # FIX 4: Add proper error handling
    except HttpError as e:
        if e.resp.status == 403:
            print(f"⚠️ YouTube API quota exceeded for {tracker['account_name']}")
        else:
            print(f"⚠️ YouTube API error: {e}")
    except Exception as e:
        print(f"Error in check_youtube_update: {e}")

# Auto-reply to DMs
@bot.event
async def on_message(message):
    # Check if it's a DM and not from the bot itself
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        # Create professional response embed
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
        # Set footer with required text
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        # Try to send the response
        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            # Can't send message back (user blocked bot or closed DMs)
            pass
    
    # --- Team Registration Handler ---
    if message.guild and not message.author.bot:
        guild_id = str(message.guild.id)
        session = active_team_collections.get(guild_id)
        if session and message.channel.id == session["post_channel_id"]:
            # Prevent registration if max slots reached
            if len(session.get("registered_teams", [])) >= session.get("max_slots", 0):
                try:
                    await message.reply(
                        f"❌ Registration closed. Maximum of {session['max_slots']} teams already registered."
                    )
                except Exception:
                    pass
                return
            # Parse team registration
            lines = message.content.splitlines()
            team_name = None
            members = []
            for line in lines:
                if line.lower().startswith("team name:"):
                    team_name = line.split(":", 1)[1].strip()
                elif line.lower().startswith("members:"):
                    member_ids = [int(m_id[3:-1]) for m_id in line.split() if m_id.startswith("<@") and m_id.endswith(">")]
                    for m_id in member_ids:
                        member = message.guild.get_member(m_id)
                        if member:
                            members.append(member)
            if not members:
                members = [m for m in message.mentions]
            if message.author not in members:
                members.insert(0, message.author)
            members = list(dict.fromkeys(members))
            # Validate
            if not team_name or len(members) != session["team_size"]:
                try:
                    await message.reply(
                        f"❌ Invalid registration format or wrong number of members ({len(members)}/{session['team_size']}).\n"
                        f"Please follow the instructions in the registration message."
                    )
                except Exception:
                    pass
                return
            # Prevent duplicate team names
            if any(t["team_name"].lower() == team_name.lower() for t in session.get("registered_teams", [])):
                try:
                    await message.reply(
                        f"❌ Team name `{team_name}` is already registered. Please choose a different name."
                    )
                except Exception:
                    pass
                return
            # Prevent member from registering in multiple teams or multiple times
            already_registered_ids = set()
            for t in session.get("registered_teams", []):
                already_registered_ids.update(t["members"])
            duplicate_members = [m for m in members if m.id in already_registered_ids]
            if duplicate_members:
                try:
                    await message.reply(
                        f"❌ The following member(s) are already registered in another team: " +
                        ", ".join(m.mention for m in duplicate_members) +
                        "\nNo member can register in more than one team."
                    )
                except Exception:
                    pass
                return
            # Post in registered_channel
            registered_channel = message.guild.get_channel(session["registered_channel_id"])
            if registered_channel:
                member_mentions = " ".join(m.mention for m in members)
                embed = discord.Embed(
                    title=f"✅ Team Registered: {team_name}",
                    description=f"**Members:** {member_mentions}",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Registered by {message.author.display_name}")
                await registered_channel.send(embed=embed)
            # Assign role
            team_role = message.guild.get_role(session["team_role_id"])
            if team_role:
                for m in members:
                    try:
                        await m.add_roles(team_role, reason=f"Team registration for {session['tournament_name']}")
                    except Exception:
                        pass
            # Save registered team
            session.setdefault("registered_teams", []).append({
                "team_name": team_name,
                "members": [m.id for m in members]
            })
            # Confirm to user
            try:
                await message.reply(f"✅ Team **{team_name}** registered and role assigned!")
            except Exception:
                pass
            return  # Do not process as command

    # Process commands (important for command functionality)
    await bot.process_commands(message)

def create_embed(title: str = None, description: str = None, color: discord.Color = discord.Color(0x3e0000)) -> discord.Embed:
    """Helper function to create consistent embeds"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.utcnow()
    )
    # Set footer with required text
    embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
    return embed

def has_announcement_permission(interaction: discord.Interaction) -> bool:
    """Check if user has announcement permissions through role or manage_messages"""
    if not interaction.guild:
        return False
    
    guild_id = str(interaction.guild.id)
    
    # Check if user has manage_messages permission
    if interaction.user.guild_permissions.manage_messages:
        return True
    
    # Check if user is server owner
    if interaction.user.id == interaction.guild.owner_id:
        return True
    
    # Check if user has announcement role
    if guild_id in guild_configs:
        role_id = guild_configs[guild_id].get("announcement_role")
        if role_id:
            return any(role.id == role_id for role in interaction.user.roles)
    
    return False

@bot.tree.command(name="set-announce-role", description="Set announcement role for this server (Admin only)")
@app_commands.describe(role="Role to use for announcement permissions")
async def set_announce_role(interaction: discord.Interaction, role: discord.Role):
    """Set the announcement role for the current server"""
    if not interaction.user.guild_permissions.manage_guild:
        embed = create_embed(
            title="❌ Permission Denied",
            description="You need 'Manage Server' permission to set announcement roles.",
            color=discord.Color(0x3e0000)
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    guild_id = str(interaction.guild.id)
    
    # Initialize guild config if needed
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
    
    # Save the role ID
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
    """Sync commands for the current server"""
    # Check if user is server owner or bot owner
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
    
    # Generate invite URL with proper scopes for troubleshooting
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
        # Sync for the current guild
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
        # Provide detailed troubleshooting for permission issues
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
        # Provide detailed troubleshooting for other issues
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
        self.datetime_input = TextInput(label="Start Time (YYYY-MM-DD HH:MM IST)",placeholder="e.g., 2025-07-10 18:30",required=True)
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

# Modal for announcement text
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
        # Create embed (removed "Official Announcement" text)
        formatted_message = f"```\n{self.message.value}\n```"
        embed = discord.Embed(
            description=formatted_message,
            color=discord.Color.gold(),
            timestamp=datetime.utcnow()
        )
        # Set footer with required text
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        
        # Prepare ping string
        ping_str = ""
        if self.ping_everyone:
            ping_str += "@everyone "
        if self.ping_here:
            ping_str += "@here "
        
        try:
            # Handle attachment if present
            files = []
            if self.attachment:
                file = await self.attachment.to_file()
                files.append(file)
            
            # Send announcement
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

# Updated announce-simple command
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

# Updated announce-attachment command
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
    """Send announcement with only an attachment"""
    if not has_announcement_permission(interaction):
        embed = create_embed(
            title="❌ Permission Denied",
            description="You need the Announcement role or 'Manage Messages' permission!",
            color=discord.Color(0x3e0000)
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    
    try:
        # Prepare ping string
        ping_str = ""
        if ping_everyone:
            ping_str += "@everyone "
        if ping_here:
            ping_str += "@here "
        
        # Process attachment
        file = await attachment.to_file()
        
        # Send announcement with only attachment
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

# Modal for DM messages
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
            # Create formatted message with larger font (using code block)
            formatted_message = (
                f"**📩 Message from {interaction.guild.name}:**\n"
                f"```\n{self.message.value}\n```\n\n"
                "For any queries or further support, contact @acroneop in our Official Server:\n"
                "https://discord.gg/xPGJCWpMbM"
            )
            
            if self.attachment:
                formatted_message += "\n\n📎 *Attachment included*"
            
            # Create embed with footer and timestamp
            embed = discord.Embed(
                description=formatted_message,
                color=discord.Color(0x3e0000),
                timestamp=datetime.utcnow()
            )
            # Set footer with required text
            embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
            
            # Handle attachment
            files = []
            if self.attachment:
                file = await self.attachment.to_file()
                files.append(file)
                embed.set_image(url=f"attachment://{file.filename}")
            
            # Send DM
            await self.user.send(embed=embed, files=files)
            
            # Confirm to sender
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

# Updated dm-user command
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

# New: DM Reply Command (Context Menu)
@bot.tree.context_menu(name="DM Reply to User")
async def dm_reply_to_user(interaction: discord.Interaction, message: discord.Message):
    """Reply to a user via DM regarding their message"""
    # Check permissions
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
    
    # Create modal for the reply
    class ReplyModal(Modal, title='DM Reply to User'):
        reply_message = TextInput(
            label='Your reply',
            style=discord.TextStyle.paragraph,
            placeholder='Type your reply here...',
            required=True
        )
        
        async def on_submit(self, interaction: discord.Interaction):
            try:
                # Create the DM message with context
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
                
                # Send the DM
                await message.author.send(embed=embed)
                
                # Confirm to the moderator
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

# Modal for welcome configuration
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
        
        # Initialize guild config if needed
        if guild_id not in guild_configs:
            guild_configs[guild_id] = {}
        
        # Save settings
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

# Updated set-welcome command
@bot.tree.command(name="set-welcome", description="Configure welcome messages (Admin only)")
@app_commands.describe(
    welcome_channel="Channel to send welcome messages",
    welcome_message="(Optional) Custom welcome DM message",
    image_url="(Optional) URL of image for welcome DM"
)
async def set_welcome(interaction: discord.Interaction, 
                     welcome_channel: discord.TextChannel,
                     welcome_message: Optional[str] = None,
                     image_url: Optional[str] = None):
    """Configure welcome system with optional custom DM message"""
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            embed=create_embed(
                title="❌ Permission Denied",
                description="You need 'Manage Server' permission",
                color=discord.Color.red()
            ),
            ephemeral=True
        )
        return
    
    guild_id = str(interaction.guild.id)
    
    # Initialize guild config
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
    
    # Save welcome channel
    guild_configs[guild_id]["welcome_channel"] = welcome_channel.id
    
    # Handle custom DM message
    if welcome_message:
        # Save custom message if provided
        guild_configs[guild_id]["welcome_dm"] = welcome_message
        msg_status = f"✅ Custom DM message set"
    else:
        # Remove custom message to use fallback
        if "welcome_dm" in guild_configs[guild_id]:
            del guild_configs[guild_id]["welcome_dm"]
        msg_status = "ℹ️ Using default DM welcome message"
    
    # Handle image URL
    if image_url:
        guild_configs[guild_id]["dm_attachment_url"] = image_url
        img_status = f"✅ Image URL set"
    else:
        if "dm_attachment_url" in guild_configs[guild_id]:
            del guild_configs[guild_id]["dm_attachment_url"]
        img_status = "ℹ️ No welcome image configured"
    
    save_config()
    
    # Build confirmation message
    confirmation = (
        f"**Welcome channel:** {welcome_channel.mention}\n"
        f"**DM Message:** {msg_status}\n"
        f"**Image:** {img_status}"
    )
    
    await interaction.response.send_message(
        embed=create_embed(
            title="✅ Welcome System Configured",
            description=confirmation,
            color=discord.Color.green()
        ),
        ephemeral=True
    )

@bot.event
async def on_member_join(member: discord.Member):
    """Send welcome messages when a member joins"""
    guild_id = str(member.guild.id)

    # Check if welcome is configured
    if guild_id not in guild_configs:
        return

    welcome_channel_id = guild_configs[guild_id].get("welcome_channel")

    # Send channel welcome
    if welcome_channel_id:
        try:
            # Ensure channel ID is int
            channel = member.guild.get_channel(int(welcome_channel_id))
            if channel:
                # --- Custom Welcome Image Generation ---
                # Get member's avatar (static, 256x256)
                avatar_asset = member.display_avatar.replace(format="png", size=256)
                avatar_bytes = await avatar_asset.read()
                avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")

                # Create base image (width 400, height 500)
                base = Image.new("RGBA", (400, 500), (255, 255, 255, 0))
                # Paste avatar in center top
                avatar_size = 256
                avatar_pos = ((400 - avatar_size) // 2, 20)
                base.paste(avatar_img.resize((avatar_size, avatar_size)), avatar_pos, avatar_img.resize((avatar_size, avatar_size)))

                draw = ImageDraw.Draw(base)

                # Load a font (fallback to default if not found)
                try:
                    font_username = ImageFont.truetype("arial.ttf", 36)
                    font_member = ImageFont.truetype("arial.ttf", 28)
                except:
                    font_username = ImageFont.load_default()
                    font_member = ImageFont.load_default()

                # Username text
                username_text = str(member)
                text_w, text_h = draw.textsize(username_text, font=font_username)
                text_x = (400 - text_w) // 2
                text_y = avatar_pos[1] + avatar_size + 20
                draw.text((text_x, text_y), username_text, font=font_username, fill=(30, 30, 30, 255))

                # Member number
                member_no = sum(1 for m in member.guild.members if not m.bot)
                member_text = f"you are our {member_no} member."
                mem_w, mem_h = draw.textsize(member_text, font=font_member)
                mem_x = (400 - mem_w) // 2
                mem_y = text_y + text_h + 10
                draw.text((mem_x, mem_y), member_text, font=font_member, fill=(120, 0, 0, 255))

                # Save to BytesIO
                img_bytes = io.BytesIO()
                base.save(img_bytes, format="PNG")
                img_bytes.seek(0)

                file = discord.File(img_bytes, filename="welcome.png")

                # Create embed with proper formatting
                welcome_text = (
                    "First click on Nexus Esports above\n"
                    "and select 'Show All Channels' so that\n"
                    "all channels become visible to you.\n\n"
                    "💕 Welcome to Nexus Esports 💕"
                )
                
                embed = discord.Embed(
                    description=(
                        f"Bro {member.mention},\n\n"  # Mention outside the code block
                        f"```\n{welcome_text}\n```"   # Instructions inside code block
                    ),
                    color=discord.Color(0x3e0000)
                )
                # Set GIF as secondary image (if you want both, use embed.set_thumbnail for GIF)
                embed.set_image(url="attachment://welcome.png")
                embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1378018158010695722/1378426905585520901/standard_2.gif")
                
                await channel.send(embed=embed, file=file)
        except Exception as e:
            print(f"⚠️ Error sending channel welcome: {e}")

    # Send DM welcome
    try:
        welcome_dm = guild_configs[guild_id].get("welcome_dm")
        dm_attachment_url = guild_configs[guild_id].get("dm_attachment_url")
        
        if welcome_dm:
            # Use configured DM
            embed = discord.Embed(
                description=welcome_dm,
                color=discord.Color(0x3e0000),
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
            
            # Add attachment if provided
            if dm_attachment_url:
                embed.set_image(url=dm_attachment_url)
            
            if member.guild.icon:
                embed.set_thumbnail(url=member.guild.icon.url)
            
            await member.send(embed=embed)
        else:
            # Fallback to fixed DM
            dm_message = (
                "🌟 Welcome to Nexus Esports! 🌟\n\n"
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
                "We're glad you're here! 🎮"
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
        pass  # User has DMs disabled
    except Exception as e:
        print(f"⚠️ Error sending welcome DM: {e}")

@bot.tree.command(name="ping", description="Test bot responsiveness")
async def ping(interaction: discord.Interaction):
    """Simple ping command with latency check"""
    latency = round(bot.latency * 1000)
    embed = create_embed(
        title="🏓 Pong!",
        description=f"Bot latency: {latency}ms",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="my-permissions", description="Check your announcement permissions")
async def check_perms(interaction: discord.Interaction):
    """Command for users to check why they can't use announcement commands"""
    has_perm = has_announcement_permission(interaction)
    perm_status = "✅ You HAVE announcement permissions!" if has_perm else "❌ You DON'T HAVE announcement permissions"
    
    # Get user's roles
    roles = ", ".join([role.name for role in interaction.user.roles]) or "No roles"
    
    # Get current guild's announcement role
    guild_id = str(interaction.guild.id)
    announce_role_id = guild_configs.get(guild_id, {}).get("announcement_role") if interaction.guild else None
    
    description = (
        f"{perm_status}\n\n"
        f"**Your roles:** {roles}\n"
        f"**Announcement role ID:** {announce_role_id or 'Not set'}\n"
        f"**Manage Messages permission:** {interaction.user.guild_permissions.manage_messages}\n"
        f"**Server Owner:** {interaction.user.id == interaction.guild.owner_id}\n\n"
        f"Contact server admins if you should have access."
    )
    
    embed = create_embed(
        title="🔑 Your Permissions",
        description=description,
        color=discord.Color.blue()
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="add-link", description="Add a professional formatted link")
@app_commands.describe(
    url="The URL to add (must start with http:// or https://)",
    title="(Optional) Title for the link",
    description="(Optional) Description text"
)
async def add_link(interaction: discord.Interaction, 
                  url: str, 
                  title: Optional[str] = None,
                  description: Optional[str] = None):
    """Add a professional formatted link with Nexus Esports styling"""
    # Validate URL format
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
        # Create the core link text
        link_text = f"[Click Here]({url})"
        
        # Build the embed description
        embed_description = f"**➤ {link_text}**"
        if description:
            embed_description += f"\n\n{description}"
        
        # Create the embed
        embed = create_embed(
            title=title if title else "🔗 Nexus Esports Link",
            description=embed_description,
            color=discord.Color(0x3e0000)
        )
        # Make the title clickable
        embed.url = url
        
        # Send the formatted link
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

# New: Reply in Channel Command
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
    """Reply to a user in the current channel with professional formatting"""
    # Check permissions
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
        # Create the arrow symbol and formatted message
        arrow = "↳"
        formatted_content = (
            f"{arrow} **Replying to {user.mention}**\n\n"
            f"```\n{message}\n```"
        )
        
        # Create embed
        embed = discord.Embed(
            description=formatted_content,
            color=discord.Color(0x3e0000),
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        # Handle message reference if provided
        reference = None
        if message_id:
            try:
                message_id_int = int(message_id)
                # Fetch the message to verify it exists
                ref_message = await interaction.channel.fetch_message(message_id_int)
                reference = ref_message.to_reference(fail_if_not_exists=False)
            except (ValueError, discord.NotFound, discord.HTTPException):
                # Send without reference if message not found
                pass
        
        # Send the reply
        await interaction.channel.send(
            embed=embed,
            reference=reference
        )
        
        # Confirm to moderator
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
    """Add social media account tracking"""
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
    
    # Initialize guild storage
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
        
            # Extract channel ID from URL
            if "youtube.com/channel/" in account_url:
                channel_id = account_url.split("youtube.com/channel/")[1].split("/")[0].split("?")[0]
            elif "youtube.com/@" in account_url:
                handle = account_url.split("youtube.com/@")[1].split("/")[0].split("?")[0]
                
                # CORRECTED PARAMETER: Use forUsername instead of forHandle
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
        
            # Get latest video ID to prevent false trigger
            search_req = youtube_service.search().list(
                part="id",
                channelId=channel_id,
                order="date",
                maxResults=1,
                type="video"
            )
            search_res = search_req.execute()
            latest_video_id = search_res['items'][0]['id']['videoId'] if search_res.get('items') else None
        
            # Get latest live video ID
            search_live = youtube_service.search().list(
                part="id",
                channelId=channel_id,
                eventType="live",
                type="video",
                maxResults=1
            ).execute()
            latest_live_id = search_live['items'][0]['id']['videoId'] if search_live.get('items') else None
        
            # Get channel statistics
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
                'url': account_url,  # Use original URL
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
    
    # Add to trackers
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
    """List active social trackers"""
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
    # Debug print
    print(f"[DEBUG] Current guild_id: {guild_id}")
    print(f"[DEBUG] social_trackers keys: {list(social_trackers.keys())}")
    trackers = social_trackers.get(guild_id, [])
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
        channel = interaction.guild.get_channel(int(tracker['post_channel']))
        count = tracker.get('last_count', 'N/A')
        if isinstance(count, int):
            count = f"{count:,}"
        embed.add_field(
            name=f"{i}. {tracker['account_name']}",
            value=(
                f"**Platform:** {tracker['platform'].capitalize()}\n"
                f"**Channel:** {channel.mention if channel else 'Not found'}\n"
                f"**Current Count:** {count}\n"
                f"[View Profile]({tracker['url']})"
            ),
            inline=False
        )
    embed.set_footer(text="Nexus Esports Social Tracker")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove-social-tracker", description="Remove a social media tracker")
@app_commands.describe(index="Tracker number to remove (see /list-social-trackers)")
async def remove_social_tracker(interaction: discord.Interaction, index: int):
    """Remove social tracker"""
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

@bot.event
async def on_guild_join(guild):
    """Handle joining new servers"""
    print(f"✅ Joined new server: {guild.name} (ID: {guild.id})")
    # Initialize default config for new server
    guild_id = str(guild.id)
    if guild_id not in guild_configs:
        guild_configs[guild_id] = {}
        save_config()
    
    # Sync commands for this new server
    try:
        await bot.tree.sync(guild=guild)
        print(f"✅ Synced commands for {guild.name}")
    except Exception as e:
        print(f"❌ Failed to sync commands for {guild.name}: {e}")


@bot.event
async def on_guild_remove(guild):
    """Handle leaving servers"""
    print(f"❌ Left server: {guild.name} (ID: {guild.id})")
    # Clean up config
    guild_id = str(guild.id)
    if guild_id in guild_configs:
        del guild_configs[guild_id]
        save_config()
    # Clean up social trackers
    if guild_id in social_trackers:
        del social_trackers[guild_id]
        save_social_trackers()

# Store active team collection sessions: {guild_id: {...}}
active_team_collections = {}

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
    """Start a team registration session for a tournament."""
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
    # Save session info
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

    # Registration instructions (short summary)
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
            title="Thank you!",
            description=f"posted in {post_channel.mention}. Teams will be posted in {registered_channel.mention}.",
            color=discord.Color.green()
        ),
        ephemeral=True
    )

# Load configs on startup
load_config()
load_social_trackers()
load_event_schedule()

# Background task for social updates

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
        await asyncio.sleep(300)  # Check every 5 minutes

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

                    if 0 <= time_diff <= 300:  # 5 minutes
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
        
        await asyncio.sleep(60)  # check every 60 seconds

async def check_youtube_update(guild_id, tracker):
    if not youtube_service:
        return

    try:
        # Get current channel stats
        request = youtube_service.channels().list(
            part='statistics,snippet',
            id=tracker['channel_id']
        )
        response = request.execute()

        if not response.get('items'):
            return

        stats = response['items'][0]['statistics']
        snippet = response['items'][0]['snippet']
        channel_name = snippet['title']
        
        # Get subscriber count
        sub_count_raw = stats.get('subscriberCount')
        
        # Handle hidden subscriber counts - don't exit, just use previous value
        if not sub_count_raw or not sub_count_raw.isdigit():
            print(f"⚠️ Hidden subscriber count for {tracker['account_name']}")
            current_subs = tracker.get('last_count', 0)
        else:
            current_subs = int(sub_count_raw)

        last_subs = tracker.get('last_count', 0)

        # Auto-fix corrupted or missing count
        if not isinstance(last_subs, int) or last_subs == 0:
            tracker['last_count'] = current_subs
            save_social_trackers()

        # If subscriber growth, send milestone alert
        elif current_subs > last_subs:
            tracker['last_count'] = current_subs
            save_social_trackers()

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

        # FIX 2: Add null check for video detection
        # Detect new video uploads
        upload_req = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            order="date",
            maxResults=1,
            type="video"
        )
        upload_res = upload_req.execute()
        if upload_res.get('items'):
            latest_video = upload_res['items'][0]
            video_id = latest_video['id']['videoId']
            video_title = latest_video['snippet']['title']
            publish_time = latest_video['snippet']['publishedAt']

            # Only notify if video_id exists and is different
            if video_id and tracker.get("last_video_id") != video_id:
                embed = discord.Embed(
                    title=f"📺 New YouTube Video: {video_title}",
                    url=f"https://youtu.be/{video_id}",
                    description=f"A new video was uploaded on {tracker['account_name']}!",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Channel", value=tracker['account_name'], inline=True)
                embed.add_field(name="Published", value=f"<t:{int(datetime.fromisoformat(publish_time.replace('Z','')).timestamp())}:R>", inline=True)
                # Move thumbnail to bottom and make it bigger
                embed.set_image(url=latest_video['snippet']['thumbnails']['high']['url'])
                # Remove set_thumbnail if present
                # Send notification
                channel = bot.get_channel(int(tracker['post_channel']))
                if channel:
                    await channel.send(embed=embed)
                tracker['last_video_id'] = video_id
                save_social_trackers()

        # FIX 3: Add null check for live detection
        # Detect if channel is live
        live_req = youtube_service.search().list(
            part="snippet",
            channelId=tracker['channel_id'],
            eventType="live",
            type="video",
            maxResults=1
        )
        live_res = live_req.execute()
        if live_res.get('items'):
            live_video = live_res['items'][0]
            live_video_id = live_video['id']['videoId']
            live_title = live_video['snippet']['title']
            live_thumb = live_video['snippet']['thumbnails']['high']['url']

            # --- Improved notification logic ---
            now = datetime.utcnow().timestamp()
            cooldown = 30 * 60  # 30 minutes in seconds
            last_notified = tracker.get('last_live_notified', 0)
            last_live_id = tracker.get('last_live_video_id')

            should_notify = False
            if live_video_id != last_live_id:
                # New live stream detected
                should_notify = True
            elif now - last_notified > cooldown:
                # Same stream, but cooldown passed
                should_notify = True

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
                    await channel.send(embed=embed)
                tracker['last_live_video_id'] = live_video_id
                tracker['last_live_notified'] = now
                save_social_trackers()

    # FIX 4: Add proper error handling
    except HttpError as e:
        if e.resp.status == 403:
            print(f"⚠️ YouTube API quota exceeded for {tracker['account_name']}")
        else:
            print(f"⚠️ YouTube API error: {e}")
    except Exception as e:
        print(f"Error in check_youtube_update: {e}")

# Auto-reply to DMs
@bot.event
async def on_message(message):
    # Check if it's a DM and not from the bot itself
    if isinstance(message.channel, discord.DMChannel) and message.author != bot.user:
        # Create professional response embed
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
        # Set footer with required text
        embed.set_footer(text="Nexus Esports Official | DM Moderators or Officials for any Query!")
        
        # Try to send the response
        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            # Can't send message back (user blocked bot or closed DMs)
            pass
    
    # --- Team Registration Handler ---
    if message.guild and not message.author.bot:
        guild_id = str(message.guild.id)
        session = active_team_collections.get(guild_id)
        if session and message.channel.id == session["post_channel_id"]:
            # Prevent registration if max slots reached
            if len(session.get("registered_teams", [])) >= session.get("max_slots", 0):
                try:
                    await message.reply(
                        f"❌ Registration closed. Maximum of {session['max_slots']} teams already registered."
                    )
                except Exception:
                    pass
                return
            # Parse team registration
            lines = message.content.splitlines()
            team_name = None
            members = []
            for line in lines:
                if line.lower().startswith("team name:"):
                    team_name = line.split(":", 1)[1].strip()
                elif line.lower().startswith("members:"):
                    member_ids = [int(m_id[3:-1]) for m_id in line.split() if m_id.startswith("<@") and m_id.endswith(">")]
                    for m_id in member_ids:
                        member = message.guild.get_member(m_id)
                        if member:
                            members.append(member)
            if not members:
                members = [m for m in message.mentions]
            if message.author not in members:
                members.insert(0, message.author)
            members = list(dict.fromkeys(members))
            # Validate
            if not team_name or len(members) != session["team_size"]:
                try:
                    await message.reply(
                        f"❌ Invalid registration format or wrong number of members ({len(members)}/{session['team_size']}).\n"
                        f"Please follow the instructions in the registration message."
                    )
                except Exception:
                    pass
                return
            # Prevent duplicate team names
            if any(t["team_name"].lower() == team_name.lower() for t in session.get("registered_teams", [])):
                try:
                    await message.reply(
                        f"❌ Team name `{team_name}` is already registered. Please choose a different name."
                    )
                except Exception:
                    pass
                return
            # Prevent member from registering in multiple teams or multiple times
            already_registered_ids = set()
            for t in session.get("registered_teams", []):
                already_registered_ids.update(t["members"])
            duplicate_members = [m for m in members if m.id in already_registered_ids]
            if duplicate_members:
                try:
                    await message.reply(
                        f"❌ The following member(s) are already registered in another team: " +
                        ", ".join(m.mention for m in duplicate_members) +
                        "\nNo member can register in more than one team."
                    )
                except Exception:
                    pass
                return
            # Post in registered_channel
            registered_channel = message.guild.get_channel(session["registered_channel_id"])
            if registered_channel:
                member_mentions = " ".join(m.mention for m in members)
                embed = discord.Embed(
                    title=f"✅ Team Registered: {team_name}",
                    description=f"**Members:** {member_mentions}",
                    color=discord.Color.green(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"Registered by {message.author.display_name}")
                await registered_channel.send(embed=embed)
            # Assign role
            team_role = message.guild.get_role(session["team_role_id"])
            if team_role:
                for m in members:
                    try:
                        await m.add_roles(team_role, reason=f"Team registration for {session['tournament_name']}")
                    except Exception:
                        pass
            # Save registered team
            session.setdefault("registered_teams", []).append({
                "team_name": team_name,
                "members": [m.id for m in members]
            })
            # Confirm to user
            try:
                await message.reply(f"✅ Team **{team_name}** registered and role assigned!")
            except Exception:
                pass
            return  # Do not process as command

    # Process commands (important for command functionality)
    await bot.process_commands(message)
