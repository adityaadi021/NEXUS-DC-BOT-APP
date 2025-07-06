import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput
import os
import json
from datetime import datetime
from typing import Optional
import asyncio
import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask
from threading import Thread

print("🚀 Bot is starting...")

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

# Social tracker storage
SOCIAL_FILE = "social_trackers.json"
social_trackers = {}

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

# Load configs on startup
load_config()
load_social_trackers()

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
    
    if not commands_synced:
        try:
            synced = await bot.tree.sync()
            commands_synced = True
            print(f"✅ Synced {len(synced)} command(s) globally")
        except Exception as e:
            print(f"❌ Command sync failed: {e}")
    
    # Start social task
    if not hasattr(bot, 'social_task'):
        bot.social_task = bot.loop.create_task(social_update_task())
        print("✅ Started social media tracking task")

# Background task for social updates
async def social_update_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await check_social_updates()
        except Exception as e:
            print(f"⚠️ Social update error: {e}")
        await asyncio.sleep(300)  # Check every 5 minutes

async def check_social_updates():
    for guild_id, trackers in list(social_trackers.items()):
        for tracker in trackers[:]:  # Use copy for safe iteration
            try:
                if tracker['platform'] == 'youtube':
                    await check_youtube_update(guild_id, tracker)
                elif tracker['platform'] == 'instagram':
                    await check_instagram_update(guild_id, tracker)
            except Exception as e:
                print(f"⚠️ Error checking {tracker['platform']} tracker: {e}")

async def check_youtube_update(guild_id, tracker):
    if not youtube_service:
        return
        
    try:
        request = youtube_service.channels().list(
            part='statistics,snippet',
            id=tracker['channel_id']
        )
        response = request.execute()
        
        if not response.get('items'):
            return
        
        stats = response['items'][0]['statistics']
        current_subs = int(stats['subscriberCount'])
        last_subs = tracker.get('last_count', 0)
        
        if current_subs > last_subs:
            # Get channel name
            channel_name = response['items'][0]['snippet']['title']
            
            # Calculate growth
            growth = current_subs - last_subs
            
            # Update tracker
            tracker['last_count'] = current_subs
            save_social_trackers()
            
            # Send notification
            channel = bot.get_channel(int(tracker['post_channel']))
            if channel:
                embed = discord.Embed(
                    title="🎉 YouTube Milestone Reached!",
                    description=(
                        f"**{channel_name}** just hit **{current_subs:,} subscribers**!\n"
                        f"`+{growth:,}` since last update"
                    ),
                    color=discord.Color.red(),
                    url=tracker['url']
                )
                embed.set_thumbnail(url="https://i.imgur.com/krKzGz0.png")
                embed.set_footer(text="Nexus Esports Social Tracker")
                await channel.send(embed=embed)
    except HttpError as e:
        print(f"YouTube API error: {e}")
    except Exception as e:
        print(f"General YouTube error: {e}")

async def check_instagram_update(guild_id, tracker):
    # Instagram requires web scraping - use carefully
    try:
        response = requests.get(tracker['url'], headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find follower count in meta tags
        meta_tag = soup.find('meta', property='og:description')
        if meta_tag:
            content = meta_tag.get('content', '')
            # Extract follower count from string like "1M Followers, 500 Following..."
            if 'Followers' in content:
                followers_str = content.split(' Followers')[0].split(' ')[-1]
                # Convert to number
                if followers_str.endswith('K'):
                    current_followers = int(float(followers_str.replace('K', '')) * 1000)
                elif followers_str.endswith('M'):
                    current_followers = int(float(followers_str.replace('M', '')) * 1000000)
                else:
                    current_followers = int(followers_str.replace(',', ''))
            else:
                return
        else:
            return
        
        last_followers = tracker.get('last_count', 0)
        
        if current_followers > last_followers:
            # Update tracker
            tracker['last_count'] = current_followers
            save_social_trackers()
            
            # Send notification
            channel = bot.get_channel(int(tracker['post_channel']))
            if channel:
                growth = current_followers - last_followers
                embed = discord.Embed(
                    title="📸 Instagram Growth!",
                    description=(
                        f"**{tracker['account_name']}** now has **{current_followers:,} followers**!\n"
                        f"`+{growth:,}` since last update"
                    ),
                    color=discord.Color.purple(),
                    url=tracker['url']
                )
                embed.set_thumbnail(url="https://i.imgur.com/vn8M9aO.png")
                embed.set_footer(text="Nexus Esports Social Tracker")
                await channel.send(embed=embed)
    except Exception as e:
        print(f"Instagram scraping failed: {e}")

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
            channel = member.guild.get_channel(welcome_channel_id)
            if channel:
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
                # Set member's avatar as thumbnail
                embed.set_thumbnail(url=member.display_avatar.url)  # <-- ADD THIS LINE
                # Set GIF
                embed.set_image(url="https://cdn.discordapp.com/attachments/1378018158010695722/1378426905585520901/standard_2.gif")
                
                await channel.send(embed=embed)
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
    app_commands.Choice(name="YouTube", value="youtube"),
    app_commands.Choice(name="Instagram", value="instagram")
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
                
                # Use channels().list with forHandle parameter
                request = youtube_service.channels().list(
                    part="id,snippet",
                    forHandle=handle
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
                    
                channel_id = response['items'][0]['id']  # Exact match
            else:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Invalid URL",
                        description="Please provide a valid YouTube channel URL",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            # Get initial stats with valid channel_id
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
                'url': f"https://www.youtube.com/channel/{channel_id}",
                'channel_id': channel_id,
                'account_name': response['items'][0]['snippet']['title'],
                'last_count': int(stats['subscriberCount']),
                'post_channel': str(post_channel.id)
            }
        
        elif platform == "instagram":
            # Extract username from URL
            if "instagram.com/" not in account_url:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Invalid URL",
                        description="Please provide a valid Instagram profile URL",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            username = account_url.split("instagram.com/")[1].split("/")[0].split("?")[0]
            clean_url = f"https://www.instagram.com/{username}/"
            
            # Get initial follower count (approximate)
            response = requests.get(clean_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            meta_tag = soup.find('meta', property='og:description')
            
            if not meta_tag:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Account Not Found",
                        description="Couldn't fetch Instagram data",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            content = meta_tag.get('content', '')
            if 'Followers' not in content:
                return await interaction.response.send_message(
                    embed=create_embed(
                        title="❌ Data Extraction Failed",
                        description="Couldn't find follower count in page",
                        color=discord.Color.red()
                    ),
                    ephemeral=True
                )
            
            followers_str = content.split(' Followers')[0].split(' ')[-1]
            
            account_info = {
                'platform': platform,
                'url': clean_url,
                'account_name': username,
                'post_channel': str(post_channel.id)
            }
            
            # Try to parse follower count
            try:
                if 'K' in followers_str:
                    account_info['last_count'] = int(float(followers_str.replace('K', ''))) * 1000
                elif 'M' in followers_str:
                    account_info['last_count'] = int(float(followers_str.replace('M', ''))) * 1000000
                else:
                    account_info['last_count'] = int(followers_str.replace(',', ''))
            except Exception as e:
                print(f"Instagram follower parse error: {e}")
                account_info['last_count'] = 0
    
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

try:
    Thread(target=run_flask).start()
    bot.run(token)
except discord.PrivilegedIntentsRequired:
    print("\n❌ PRIVILEGED INTENTS REQUIRED ❌")
    print("1. Go to https://discord.com/developers/applications")
    print("2. Select your application")
    print("3. Navigate to Bot > Privileged Gateway Intents")
    print("4. ENABLE 'MESSAGE CONTENT INTENT' and 'SERVER MEMBERS INTENT'")
    print("5. Save changes and restart your bot\n")
except discord.LoginFailure:
    print("❌ Invalid token. Check your DISCORD_TOKEN")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
