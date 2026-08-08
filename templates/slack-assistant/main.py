import json
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import logging
from difflib import SequenceMatcher

INTRO_PROMPT = "Hi! I'm your Slack assistant. I can help you list channels, send messages, read recent messages, and more. What would you like to do?"

class SlackEmailCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    slack_client: WebClient = None
    user_info: dict = None
    cached_channels: list = None

    #{{register capability}}

    async def initialize_slack(self):
        """Initialize Slack client and get user info"""
        try:
            slack_token = self.capability_worker.get_slack_key()
            
            if not slack_token:
                await self.capability_worker.speak(
                    "Your Slack account is not linked with Openhome. "
                    "Please go to app.openhome.com/dashboard/settings to link your Slack account first."
                )
                return False
            
            self.slack_client = WebClient(token=slack_token)
            
            # Get current user info
            response = self.slack_client.auth_test()
            self.user_info = {
                'user_id': response['user_id'],
                'user_name': response['user'],
                'team_id': response['team_id'],
                'team_name': response['team']
            }
            
            await self.capability_worker.speak(
                f"Connected to Slack workspace: {self.user_info['team_name']}"
            )
            return True
            
        except SlackApiError as e:
            logging.error(f"Slack API Error: {e.response['error']}")
            await self.capability_worker.speak(
                "There was an error connecting to Slack. Please try again or check your connection."
            )
            return False
        except Exception as e:
            logging.error(f"Error initializing Slack: {e}")
            await self.capability_worker.speak(
                "Failed to connect to Slack. Please make sure your account is properly linked."
            )
            return False

    def normalize_channel_name(self, name: str) -> str:
        """Normalize channel name for matching"""
        # Remove common prefixes and special characters
        name = name.lower().strip()
        name = name.replace('#', '')
        name = name.replace('channel', '').strip()
        name = name.replace('the', '').strip()
        # Replace spaces with hyphens (common in Slack)
        name = name.replace(' ', '-')
        return name

    def fuzzy_match_channel(self, user_input: str, channels: list) -> dict:
        """
        Intelligently match user input to a channel name using multiple strategies:
        1. Exact match (after normalization)
        2. Contains match
        3. Fuzzy string matching
        4. LLM-based matching for complex cases
        """
        normalized_input = self.normalize_channel_name(user_input)
        
        best_match = None
        best_score = 0
        
        for channel in channels:
            channel_name = channel['name'].lower()
            
            # Strategy 1: Exact match after normalization
            if normalized_input == channel_name:
                return channel
            
            # Strategy 2: Direct substring match
            if normalized_input in channel_name or channel_name in normalized_input:
                return channel
            
            # Strategy 3: Fuzzy matching (handles typos and variations)
            # Compare both with and without hyphens
            similarity1 = SequenceMatcher(None, normalized_input, channel_name).ratio()
            similarity2 = SequenceMatcher(None, normalized_input.replace('-', ''), channel_name.replace('-', '')).ratio()
            
            max_similarity = max(similarity1, similarity2)
            
            if max_similarity > best_score:
                best_score = max_similarity
                best_match = channel
        
        # Return best match if similarity is above threshold
        if best_score > 0.6:  # 60% similarity threshold
            return best_match
        
        return None

    async def smart_channel_search(self, user_input: str, channels: list) -> dict:
        """Use LLM to intelligently match channel names when fuzzy matching fails"""
        channel_names = [ch['name'] for ch in channels]
        
        prompt = f"""The user said: "{user_input}"

Here are the available Slack channels:
{', '.join(channel_names)}

Which channel is the user most likely referring to? Consider:
- "new channel" matches "new-channel"
- "general" matches "general"
- "team updates" matches "team-updates"
- Ignore words like "the", "channel", etc.

Respond with ONLY the exact channel name from the list, or "NONE" if no good match exists.
Do not include any explanation, just the channel name."""

        response = self.capability_worker.text_to_text_response(prompt).strip()
        
        # Find the channel that matches the LLM response
        for channel in channels:
            if channel['name'].lower() == response.lower():
                return channel
        
        return None

    async def get_channel_intelligently(self, user_input: str) -> dict:
        """
        Intelligently find a channel using multiple strategies
        """
        # Get channels if not cached
        if not self.cached_channels:
            try:
                response = self.slack_client.conversations_list(
                    types="public_channel,private_channel",
                    limit=100
                )
                self.cached_channels = [ch for ch in response['channels'] if ch.get('is_member', False)]
            except SlackApiError as e:
                logging.error(f"Error getting channels: {e.response['error']}")
                return None
        
        if not self.cached_channels:
            return None
        
        # Try fuzzy matching first (fast)
        channel = self.fuzzy_match_channel(user_input, self.cached_channels)
        
        if channel:
            logging.info(f"Fuzzy match found: {channel['name']}")
            return channel
        
        # Fall back to LLM-based matching (slower but more intelligent)
        channel = await self.smart_channel_search(user_input, self.cached_channels)
        
        if channel:
            logging.info(f"LLM match found: {channel['name']}")
            return channel
        
        return None

    async def list_channels(self):
        """List all available channels"""
        try:
            # Get public channels
            channels_response = self.slack_client.conversations_list(
                types="public_channel,private_channel",
                limit=100
            )
            
            channels = channels_response['channels']
            
            if not channels:
                await self.capability_worker.speak("You don't have access to any channels.")
                return None
            
            # Filter channels user is a member of
            my_channels = [ch for ch in channels if ch.get('is_member', False)]
            
            # Cache the channels
            self.cached_channels = my_channels
            
            if not my_channels:
                await self.capability_worker.speak("You haven't joined any channels yet.")
                return None
            
            # Create a readable list with proper formatting for speech
            if len(my_channels) <= 10:
                # Convert hyphenated names to spaces for better speech
                readable_names = [ch['name'].replace('-', ' ').replace('_', ' ') for ch in my_channels]
                channels_text = "Here are your channels: " + ", ".join(readable_names)
            else:
                readable_names = [ch['name'].replace('-', ' ').replace('_', ' ') for ch in my_channels[:10]]
                channels_text = f"You have {len(my_channels)} channels. Here are the first 10: " + ", ".join(readable_names)
            
            await self.capability_worker.speak(channels_text)
            
            return my_channels
            
        except SlackApiError as e:
            logging.error(f"Error listing channels: {e.response['error']}")
            await self.capability_worker.speak("I couldn't retrieve your channels. Please try again.")
            return None

    async def list_direct_messages(self):
        """List recent direct message conversations"""
        try:
            # Get DM conversations
            dm_response = self.slack_client.conversations_list(
                types="im",
                limit=20
            )
            
            dms = dm_response['channels']
            
            if not dms:
                await self.capability_worker.speak("You don't have any direct message conversations.")
                return None
            
            # Get user info for each DM
            dm_list = []
            for dm in dms[:5]:  # Limit to 5 most recent
                try:
                    user_info = self.slack_client.users_info(user=dm['user'])
                    user_name = user_info['user']['real_name'] or user_info['user']['name']
                    dm_list.append({
                        'id': dm['id'],
                        'user_name': user_name,
                        'user_id': dm['user']
                    })
                except:
                    continue
            
            if dm_list:
                names = ", ".join([dm['user_name'] for dm in dm_list])
                await self.capability_worker.speak(
                    f"Your recent direct messages are with: {names}"
                )
                return dm_list
            else:
                await self.capability_worker.speak("No recent direct messages found.")
                return None
                
        except SlackApiError as e:
            logging.error(f"Error listing DMs: {e.response['error']}")
            await self.capability_worker.speak("I couldn't retrieve your direct messages.")
            return None

    async def send_message_to_channel(self, channel_id: str, message: str):
        """Send a message to a specific channel"""
        try:
            response = self.slack_client.chat_postMessage(
                channel=channel_id,
                text=message
            )
            
            if response['ok']:
                await self.capability_worker.speak("Message sent successfully!")
                return True
            else:
                await self.capability_worker.speak("Failed to send the message.")
                return False
                
        except SlackApiError as e:
            logging.error(f"Error sending message: {e.response['error']}")
            error_msg = e.response['error']
            
            if error_msg == 'channel_not_found':
                await self.capability_worker.speak("Channel not found. Please check the channel name.")
            elif error_msg == 'not_in_channel':
                await self.capability_worker.speak("You're not a member of this channel.")
            else:
                await self.capability_worker.speak("I couldn't send the message. Please try again.")
            
            return False

    async def read_recent_messages(self, channel_id: str, limit: int = 5):
        """Read recent messages from a channel"""
        try:
            response = self.slack_client.conversations_history(
                channel=channel_id,
                limit=limit
            )
            
            messages = response['messages']
            
            if not messages:
                await self.capability_worker.speak("No messages found in this channel.")
                return None
            
            # Format messages for speech
            message_summaries = []
            for msg in reversed(messages):  # Show oldest first
                # Skip bot messages and system messages
                if msg.get('subtype') in ['bot_message', 'channel_join', 'channel_leave']:
                    continue
                
                user_id = msg.get('user')
                text = msg.get('text', '')
                
                if user_id and text:
                    try:
                        user_info = self.slack_client.users_info(user=user_id)
                        user_name = user_info['user']['real_name'] or user_info['user']['name']
                        message_summaries.append(f"{user_name} said: {text}")
                    except:
                        message_summaries.append(f"Someone said: {text}")
            
            if message_summaries:
                # Limit to 3 messages for voice readability
                messages_text = "Recent messages: " + ". ".join(message_summaries[:3])
                await self.capability_worker.speak(messages_text)
                return message_summaries
            else:
                await self.capability_worker.speak("No readable messages found.")
                return None
                
        except SlackApiError as e:
            logging.error(f"Error reading messages: {e.response['error']}")
            await self.capability_worker.speak("I couldn't read the messages from this channel.")
            return None

    async def interactive_send_message(self):
        """Interactive flow to send a message with retry logic"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            # Ask which channel
            if retry_count == 0:
                await self.capability_worker.speak("Which channel would you like to send a message to? You can say 'list channels' to hear them again, or 'cancel' to go back.")
            else:
                await self.capability_worker.speak("Please try again. Which channel? Say 'list channels' to hear them, or 'cancel' to go back.")
            
            channel_input = await self.capability_worker.user_response()
            channel_input_lower = channel_input.lower()
            
            # Check for special commands
            if 'cancel' in channel_input_lower or 'exit' in channel_input_lower or 'back' in channel_input_lower:
                await self.capability_worker.speak("Cancelled. What else can I help you with?")
                return
            
            if 'list' in channel_input_lower:
                await self.list_channels()
                continue
            
            # Find the channel intelligently
            channel = await self.get_channel_intelligently(channel_input)
            
            if not channel:
                retry_count += 1
                if retry_count < max_retries:
                    await self.capability_worker.speak(
                        f"I couldn't find a channel matching '{channel_input}'. "
                    )
                else:
                    await self.capability_worker.speak(
                        "I'm having trouble finding that channel. Let's try something else."
                    )
                    return
                continue
            
            # Confirm the channel match
            readable_name = channel['name'].replace('-', ' ').replace('_', ' ')
            confirm_channel = await self.capability_worker.run_confirmation_loop(
                f"I found the channel {readable_name}. Is this correct?"
            )
            
            if not confirm_channel:
                retry_count += 1
                continue
            
            # Ask for the message
            await self.capability_worker.speak(f"What message would you like to send to {readable_name}?")
            message_text = await self.capability_worker.user_response()
            
            # Confirm before sending
            confirm = await self.capability_worker.run_confirmation_loop(
                f"You want to send: {message_text}, to {readable_name}. Should I send it?"
            )
            
            if confirm:
                await self.send_message_to_channel(channel['id'], message_text)
                return
            else:
                await self.capability_worker.speak("Message cancelled. What else can I help you with?")
                return

    async def interactive_read_messages(self):
        """Interactive flow to read messages from a channel with retry logic"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            # Ask which channel
            if retry_count == 0:
                await self.capability_worker.speak("Which channel would you like to read messages from? Say 'list channels' to hear them, or 'cancel' to go back.")
            else:
                await self.capability_worker.speak("Please try again. Which channel? Say 'list channels' or 'cancel'.")
            
            channel_input = await self.capability_worker.user_response()
            channel_input_lower = channel_input.lower()
            
            # Check for special commands
            if 'cancel' in channel_input_lower or 'exit' in channel_input_lower or 'back' in channel_input_lower:
                await self.capability_worker.speak("Cancelled. What else can I help you with?")
                return
            
            if 'list' in channel_input_lower:
                await self.list_channels()
                continue
            
            # Find the channel intelligently
            channel = await self.get_channel_intelligently(channel_input)
            
            if not channel:
                retry_count += 1
                if retry_count < max_retries:
                    await self.capability_worker.speak(
                        f"I couldn't find a channel matching '{channel_input}'."
                    )
                else:
                    await self.capability_worker.speak(
                        "I'm having trouble finding that channel. Let's try something else."
                    )
                    return
                continue
            
            # Confirm and read
            readable_name = channel['name'].replace('-', ' ').replace('_', ' ')
            await self.capability_worker.speak(f"Reading recent messages from {readable_name}")
            await self.read_recent_messages(channel['id'], limit=5)
            return

    async def search_users(self, query: str):
        """Search for users in the workspace"""
        try:
            response = self.slack_client.users_list(limit=100)
            users = response['members']
            
            # Filter users matching the query
            matching_users = []
            query_lower = query.lower()
            
            for user in users:
                if user.get('deleted') or user.get('is_bot'):
                    continue
                
                name = user.get('real_name', '').lower()
                username = user.get('name', '').lower()
                
                if query_lower in name or query_lower in username:
                    matching_users.append({
                        'id': user['id'],
                        'name': user.get('real_name') or user.get('name'),
                        'username': user.get('name')
                    })
            
            if matching_users:
                names = ", ".join([u['name'] for u in matching_users[:5]])
                await self.capability_worker.speak(f"I found these users: {names}")
                return matching_users
            else:
                await self.capability_worker.speak(f"No users found matching '{query}'")
                return None
                
        except SlackApiError as e:
            logging.error(f"Error searching users: {e.response['error']}")
            await self.capability_worker.speak("I couldn't search for users.")
            return None

    async def main_menu_loop(self):
        """Continuous loop for Slack operations until user says exit"""
        
        while True:
            await self.capability_worker.speak(
                "What would you like to do? You can list channels, send a message, read messages, search users, or say exit to leave Slack assistant."
            )
            
            user_choice = await self.capability_worker.user_response()
            user_choice_lower = user_choice.lower()
            
            # Check for exit commands
            if any(word in user_choice_lower for word in ['exit', 'quit', 'goodbye', 'bye', 'stop', 'done', 'leave']):
                await self.capability_worker.speak("Goodbye! Come back anytime you need help with Slack.")
                break
            
            # Parse user intent using LLM
            intent_prompt = f"""The user said: "{user_choice}"

Determine which Slack action they want to perform. Respond with ONLY ONE of these options:
- list_channels
- list_dms
- send_message
- read_messages
- search_users
- help

Consider variations like:
- "show channels" or "what channels" -> list_channels
- "send a message" or "post message" -> send_message
- "read messages" or "check messages" -> read_messages

Respond with just the action name, nothing else."""

            intent = self.capability_worker.text_to_text_response(intent_prompt).strip().lower()
            
            try:
                if 'list_channels' in intent or 'channels' in user_choice_lower:
                    await self.list_channels()
                
                elif 'list_dms' in intent or 'direct message' in user_choice_lower or 'dm' in user_choice_lower:
                    await self.list_direct_messages()
                
                elif 'send_message' in intent or 'send' in user_choice_lower or 'post' in user_choice_lower:
                    await self.interactive_send_message()
                
                elif 'read_messages' in intent or 'read' in user_choice_lower or 'check' in user_choice_lower:
                    await self.interactive_read_messages()
                
                elif 'search_users' in intent or 'search' in user_choice_lower or 'find user' in user_choice_lower:
                    await self.capability_worker.speak("Who would you like to search for?")
                    search_query = await self.capability_worker.user_response()
                    await self.search_users(search_query)
                
                else:
                    await self.capability_worker.speak(
                        "I can help you with: listing channels, sending messages, reading messages, or searching for users. What would you like to do?"
                    )
                    
            except Exception as e:
                logging.error(f"Error in main menu: {e}")
                await self.capability_worker.speak(
                    "I encountered an error. Let's try again. What would you like to do?"
                )

    async def my_slack(self):
        """Main entry point for Slack capability"""
        # Initialize Slack connection
        initialized = await self.initialize_slack()
        
        if not initialized:
            self.capability_worker.resume_normal_flow()
            return
        
        # Welcome message
        await self.capability_worker.speak(INTRO_PROMPT)
        
        # Run continuous loop
        await self.main_menu_loop()
        
        # Final message
        await self.capability_worker.speak(
            "Thank you for using the Slack assistant!"
        )
        
        # Resume normal workflow
        self.capability_worker.resume_normal_flow()

    def call(self, worker: AgentWorker):
        # Initialize the worker and capability worker
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)

        # Start the Slack functionality
        self.worker.session_tasks.create(self.my_slack())