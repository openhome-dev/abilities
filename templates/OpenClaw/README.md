# OpenClaw Template - Build Custom Computer Control Abilities

## What This Is
**This is a template ability** that enables you to create custom voice-controlled computer automation using OpenClaw. Use this as a starting point to build abilities that control your local machine through OpenHome.

## What You Can Build
Examples of abilities you could create with this template:
- Application launcher and manager
- System monitoring and diagnostics
- File and folder automation
- Development environment controller
- Custom workflow automations
- Smart home integration via computer
- Screenshot and screen recording tools
- Clipboard and text manipulation

## Template Trigger Words
This template uses generic triggers - **you should customize these** for your specific ability:
- Any computer control request
- Configure your own trigger words in OpenHome Live editor or when creating your ability.

## Requirements

### 1. OpenClaw Installation & Configuration
OpenClaw must be installed and configured on your local machine with an LLM API key.

**Install OpenClaw:**
```bash
npm install -g openclaw@latest
```

**Initialize OpenClaw Daemon:**
```bash
openclaw onboard --install-daemon
```

**Configure with LLM API Key:**
Follow OpenClaw's configuration steps to add your LLM API key (OpenAI, Anthropic, etc.)

### 2. Download OpenClaw Client
Download the OpenHome client for OpenClaw based on your operating system:

**[Download Link](https://drive.google.com/drive/folders/10qK75I-bFB2D98YJ6dH3tQFsvEk44Y7-)**

Choose the appropriate version:
- Windows: `.exe` installer
- macOS: `.dmg` or `.app` file
- Linux: AppImage or `.deb`

### 3. Client Setup & Connection
1. **Run the downloaded client**
   - **Windows**: Run the .exe, allow permissions if prompted
   - **macOS**: If blocked, go to System Settings → Privacy & Security → "Open Anyway"
   - **Linux**: `chmod +x` and run, grant required permissions

2. **Copy your OpenHome API Key**
   - Go to [OpenHome Dashboard → Settings → API Keys](https://app.openhome.com/dashboard/settings)
   - Copy your API key

3. **Connect the client**
   - Paste the API key into the OpenClaw client app
   - Click "Connect"
   - Wait for "welcome" message in logs (confirms successful connection)

## Using This Template

### Step 1: Get the Template
Find the OpenClaw template ability from:
- OpenHome Dashboard abilities library, OR
- [GitHub Repository](https://github.com/OpenHome-dev/abilities)

### Step 2: Customize for Your Use Case
This template provides the basic structure. Modify it to:

1. **Define your trigger words** in `config.json`:
   ```json
   {
     "unique_name": "my_custom_openclaw_ability",
     "matching_hotwords": [
       "open my development environment",
       "start coding session",
       "check system health"
     ]
   }
   ```

2. **Customize the command logic** in `main.py`:
   ```python
   async def first_function(self):
       user_inquiry = await self.capability_worker.wait_for_complete_transcription()
       
       # Add your custom logic here
       # Example: Parse specific commands, validate input, add confirmations
       
       await self.capability_worker.speak(f"Sending Inquiry to OpenClaw")
       response = await self.capability_worker.exec_local_command(user_inquiry)
       
       # Process the response as needed
       result = self.capability_worker.text_to_text_response(...)
       await self.capability_worker.speak(result)
       
       self.capability_worker.resume_normal_flow()
   ```

3. **Add command validation** (optional but recommended):
   ```python
   # Example: Prevent dangerous commands
   dangerous_keywords = ["rm -rf", "format", "delete system"]
   if any(keyword in user_inquiry.lower() for keyword in dangerous_keywords):
       await self.capability_worker.speak("I can't execute that command for safety.")
       return
   ```

4. **Implement multi-step workflows** (optional):
   ```python
   # Example: Confirm before executing
   await self.capability_worker.speak("This will restart your computer. Confirm?")
   confirmation = await self.capability_worker.user_response()
   if "yes" in confirmation.lower():
       response = await self.capability_worker.exec_local_command("restart")
   ```

## How It Works
1. User speaks a computer control command
2. OpenHome captures the voice input as text
3. Ability sends the command to your local OpenClaw client
4. OpenClaw executes the command on your computer
5. OpenClaw returns the result (success/failure/output)
6. AI converts the result into a natural spoken response
7. AI speaks the result (max 15 words, one sentence)

**Smart Features:**
- **Natural Language Processing**: Send plain English commands
- **Automatic Response Formatting**: Technical output → conversational speech
- **Timeout Protection**: 10-second max wait prevents hanging
- **Error Handling**: Clear feedback when commands fail
- **Cross-Platform**: Works on Windows, macOS, and Linux

## Template Usage Examples

These examples show how the **unmodified template** would work. Customize the logic for your specific use case.

### Basic Template Behavior
> **User:** "open Slack"  
> **AI:** "Sending Inquiry to OpenClaw"  
> *(OpenClaw executes on local machine)*  
> **AI:** "Slack is now open."

### With System Information
> **User:** "check disk usage"  
> **AI:** "Sending Inquiry to OpenClaw"  
> *(OpenClaw queries system)*  
> **AI:** "Disk usage is at 42 percent."

### Handling Errors
> **User:** "open NonExistentApp"  
> **AI:** "Sending Inquiry to OpenClaw"  
> *(OpenClaw fails to find app)*  
> **AI:** "I couldn't find NonExistentApp on this machine."

### Custom Ability Example
After customizing the template with multi-step logic:

> **User:** "start my morning routine"  
> **AI:** "Opening Calendar, Email, and Slack"  
> *(Executes 3 commands sequentially)*  
> **AI:** "Morning apps are ready."

## Core Template Function

The template provides one essential function for sending commands to your local machine:

### `exec_local_command()`
Sends a command/inquiry to your local OpenClaw client and returns the response.

**Function Signature:**
```python
async def exec_local_command(
    self,
    command: str | dict,
    target_id: str | None = None,
    timeout: float = 10.0
)
```

**Parameters:**
- `command` (str | dict): **Required.** The inquiry message or command for OpenClaw
- `target_id` (str | None): **Optional.** Target device identifier (default: "laptop")
- `timeout` (float): **Optional.** Max seconds to wait for response (default: 10.0)

**Returns:**
- `str`: Response from OpenClaw execution (success message, error, or command output)

**Template Usage:**
```python
# Basic usage (as shown in template)
response = await self.capability_worker.exec_local_command(user_inquiry)

# With custom timeout for long-running commands
response = await self.capability_worker.exec_local_command(
    "compile large project",
    timeout=30.0
)

# With specific target device
response = await self.capability_worker.exec_local_command(
    "check battery status",
    target_id="laptop"
)
```

## How the Template Works

1. **User speaks a command** → Voice input captured by OpenHome
2. **Template receives transcription** → `wait_for_complete_transcription()`
3. **Command sent to OpenClaw** → `exec_local_command(user_inquiry)`
4. **OpenClaw executes locally** → Runs on your computer with your permissions
5. **Response returned** → Success/failure/output comes back from OpenClaw
6. **AI formats for speech** → Converts technical output to natural language (max 15 words)
7. **AI speaks result** → User hears the outcome

**Response Formatting Rules (Built into Template):**
The template automatically converts technical output into conversational speech:
- ✅ "Slack is now open." (action confirmed)
- ✅ "Disk usage is at 42 percent." (useful info extracted)
- ✅ "I couldn't find Slack on this machine." (error explained)
- ❌ Avoids: JSON blocks, markdown, code snippets, raw command output
- **Constraint**: Maximum 1 sentence, 15 words or less

## Example Abilities You Can Build

### 1. Development Environment Controller
```python
# Trigger: "start coding session"
# Opens IDE, starts local servers, opens documentation
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    commands = [
        "open Visual Studio Code",
        "start local dev server on port 3000",
        "open browser to localhost:3000"
    ]
    
    for cmd in commands:
        await self.capability_worker.exec_local_command(cmd)
    
    await self.capability_worker.speak("Development environment is ready.")
    self.capability_worker.resume_normal_flow()
```

### 2. System Health Monitor
```python
# Trigger: "check system health"
# Reports CPU, memory, disk, and battery status
async def first_function(self):
    metrics = [
        ("CPU usage", "get cpu usage"),
        ("Memory usage", "get memory usage"),
        ("Disk space", "get disk usage"),
        ("Battery level", "get battery level")
    ]
    
    report = []
    for name, cmd in metrics:
        response = await self.capability_worker.exec_local_command(cmd)
        report.append(f"{name}: {response}")
    
    await self.capability_worker.speak(", ".join(report))
    self.capability_worker.resume_normal_flow()
```

### 3. Smart Screenshot Tool
```python
# Trigger: "take screenshot of active window"
# Captures, saves with timestamp, confirms location
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    # Extract what to capture
    if "full screen" in user_inquiry.lower():
        cmd = "screenshot fullscreen save to ~/Desktop"
    elif "active window" in user_inquiry.lower():
        cmd = "screenshot active window save to ~/Desktop"
    else:
        cmd = "screenshot selection save to ~/Desktop"
    
    response = await self.capability_worker.exec_local_command(cmd, timeout=15.0)
    
    # Parse filename from response and confirm
    await self.capability_worker.speak(f"Screenshot saved: {response}")
    self.capability_worker.resume_normal_flow()
```

### 4. Application Manager with Confirmation
```python
# Trigger: "close all browsers"
# Lists open browsers, asks confirmation, closes them
async def first_function(self):
    # Get list of open browsers
    response = await self.capability_worker.exec_local_command("list open browsers")
    
    if "none" in response.lower():
        await self.capability_worker.speak("No browsers are open.")
        self.capability_worker.resume_normal_flow()
        return
    
    # Confirm before closing
    await self.capability_worker.speak(f"Found: {response}. Close all?")
    confirmation = await self.capability_worker.user_response()
    
    if "yes" in confirmation.lower():
        await self.capability_worker.exec_local_command("close all browsers")
        await self.capability_worker.speak("All browsers closed.")
    else:
        await self.capability_worker.speak("Cancelled.")
    
    self.capability_worker.resume_normal_flow()
```

## Troubleshooting

### OpenClaw Client Won't Connect
- Verify API key is correct (copy from Dashboard → Settings → API Keys)
- Check if daemon is running: `openclaw status`
- Restart the OpenClaw client app
- Check logs in the client for error messages

### Commands Timeout or Fail
- Increase timeout: `exec_local_command(command, timeout=20.0)`
- Check OpenClaw daemon status: `openclaw status`
- Verify the command is valid for your OS
- Check OpenClaw client logs for execution errors

### Permission Errors (macOS)
- Go to System Settings → Privacy & Security
- Find the blocked app notification
- Click "Open Anyway"
- Grant permissions when prompted (Accessibility, Automation, etc.)

### Commands Not Executing
- Verify OpenClaw client shows "Connected" status
- Test a simple command like "what time is it"
- Check if the ability is correctly registered in OpenHome
- Review OpenClaw client logs for connection issues

## Security & Privacy
- OpenClaw runs locally on your machine — no commands are sent to external servers
- API key authenticates OpenHome → OpenClaw connection
- You control what commands the ability can execute
- Review all permissions carefully when installing the client

## Best Practices for Building with This Template

### 1. Define Clear Trigger Words
Choose specific, unambiguous trigger phrases in `config.json`:
```json
{
  "matching_hotwords": [
    "start development session",
    "open my coding setup",
    "launch dev environment"
  ]
}
```

Avoid overly generic triggers that might conflict with other abilities.

### 2. Add Command Validation
Protect users from accidentally running dangerous commands:
```python
# Blacklist approach
DANGEROUS_COMMANDS = ["rm -rf", "format", "delete system", "shutdown -h now"]

if any(danger in user_inquiry.lower() for danger in DANGEROUS_COMMANDS):
    await self.capability_worker.speak("I can't execute that for safety reasons.")
    return
```

### 3. Implement Confirmation for Destructive Actions
```python
if "restart" in user_inquiry.lower() or "shutdown" in user_inquiry.lower():
    await self.capability_worker.speak("This will restart your computer. Are you sure?")
    confirm = await self.capability_worker.user_response()
    if "yes" not in confirm.lower():
        await self.capability_worker.speak("Cancelled.")
        return
```

### 4. Handle Timeouts Appropriately
Adjust timeout based on expected command duration:
```python
# Quick commands (default 10s is fine)
response = await self.capability_worker.exec_local_command("open Chrome")

# Long-running commands (increase timeout)
response = await self.capability_worker.exec_local_command(
    "compile entire project",
    timeout=60.0  # 1 minute
)
```

### 5. Parse and Format Responses
Don't just echo raw OpenClaw output:
```python
response = await self.capability_worker.exec_local_command("get battery level")

# Bad: "Battery: 73% (charging, 2:15 remaining)"
# Good: Extract just the useful info
battery_level = extract_percentage(response)  # Your parsing logic
await self.capability_worker.speak(f"Battery is at {battery_level} percent.")
```

### 6. Add Error Handling
```python
try:
    response = await self.capability_worker.exec_local_command(
        user_inquiry,
        timeout=15.0
    )
    
    if "error" in response.lower() or "failed" in response.lower():
        await self.capability_worker.speak("That command didn't work. Try something else.")
    else:
        # Process successful response
        ...
        
except asyncio.TimeoutError:
    await self.capability_worker.speak("That command took too long. It might still be running.")
except Exception as e:
    self.worker.editor_logging_handler.error(f"Command failed: {e}")
    await self.capability_worker.speak("Something went wrong. Check the logs.")
```

### 7. Chain Commands for Complex Workflows
```python
# Example: "prepare for meeting"
workflow = [
    ("Opening calendar", "open Calendar app"),
    ("Starting video", "open Zoom"),
    ("Opening notes", "open Notes app"),
]

for description, command in workflow:
    await self.capability_worker.speak(description)
    await self.capability_worker.exec_local_command(command)
    await asyncio.sleep(1)  # Brief pause between commands

await self.capability_worker.speak("Ready for your meeting.")
```

## Template Code Walkthrough

### Key Components

**1. Wait for User Input:**
```python
user_inquiry = await self.capability_worker.wait_for_complete_transcription()
```
Gets the full voice command before processing.

**2. Send to OpenClaw:**
```python
response = await self.capability_worker.exec_local_command(user_inquiry)
```
Sends command to local machine, returns result.

**3. Format Response:**
```python
check_response_system_prompt = """You are a voice assistant..."""
result = self.capability_worker.text_to_text_response(
    "Original user request: '%s'. Command result: %s" % (user_inquiry, response),
    history,
    check_response_system_prompt,
)
```
LLM converts technical output → natural speech (15 words max).

**4. Speak and Resume:**
```python
await self.capability_worker.speak(result)
self.capability_worker.resume_normal_flow()
```
Delivers result and returns control to main assistant.

### Modifying the Template

**To add pre-processing:**
```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    # ⬇️ ADD YOUR LOGIC HERE
    if "screenshot" in user_inquiry.lower():
        user_inquiry = "take screenshot and save to desktop"
    # ⬆️
    
    response = await self.capability_worker.exec_local_command(user_inquiry)
    # ... rest of template
```

**To add post-processing:**
```python
async def first_function(self):
    # ... template code to get response
    
    # ⬇️ ADD YOUR LOGIC HERE
    if "screenshot saved" in response.lower():
        # Extract filename and offer to open
        await self.capability_worker.speak("Screenshot saved. Open it?")
        confirm = await self.capability_worker.user_response()
        if "yes" in confirm.lower():
            await self.capability_worker.exec_local_command("open last screenshot")
    # ⬆️
    
    self.capability_worker.resume_normal_flow()
```

**To add multi-turn interaction:**
```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    # First command
    response1 = await self.capability_worker.exec_local_command(user_inquiry)
    await self.capability_worker.speak(response1)
    
    # Ask for follow-up
    await self.capability_worker.speak("What else should I do?")
    next_command = await self.capability_worker.user_response()
    
    # Second command
    response2 = await self.capability_worker.exec_local_command(next_command)
    await self.capability_worker.speak(response2)
    
    self.capability_worker.resume_normal_flow()
```

## Important Template Notes

### This is a Starting Point
- **The template is intentionally minimal** — it's designed to be modified
- Don't use it as-is for production — customize it for your use case!
- The real power comes from your specific implementation

### Security Considerations
- OpenClaw runs with **your user permissions** on local machine
- Commands execute exactly as if you typed them in terminal
- **Always add validation** for any user-provided input
- Use **confirmation prompts** for destructive operations (restart, delete, etc.)
- Review all commands before enabling in production

### Client Must Stay Running
- OpenClaw client must run in background for ability to work
- If client disconnects, commands will fail
- Monitor client logs for connection issues
- Consider adding retry logic for failed commands

### Response Formatting
- 15-word limit ensures concise voice responses
- Technical output is automatically cleaned up by LLM
- You can modify the formatting prompt for different styles
- Balance between information density and speakability

### Testing Strategy
1. Test with simple, safe commands first ("what time is it")
2. Verify timeout handling with long-running commands
3. Test error scenarios (invalid commands, disconnected client)
4. Check response formatting with various output types
5. **Test on target OS** (commands vary by platform: Windows/macOS/Linux)

## Technical Architecture
```
Voice Input → OpenHome Ability → exec_local_command()
                                        ↓
                                 OpenClaw Client
                                   (via WebSocket)
                                        ↓
                                 OpenClaw Daemon
                                  (with LLM API)
                                        ↓
                                Local System Execution
                                  (apps, files, etc.)
                                        ↓
                        Response ← AI Formatting ← Template
```

## Links & Resources

**Required Downloads:**
- **[OpenClaw Client](https://drive.google.com/drive/folders/10qK75I-bFB2D98YJ6dH3tQFsvEk44Y7-)** — Download for your OS (required)

**OpenHome:**
- [Dashboard](https://app.openhome.com/dashboard)
- [API Key Management](https://app.openhome.com/dashboard/settings) — Get your API key here
- [Abilities Library](https://app.openhome.com/dashboard/abilities)

**OpenClaw:**
- CLI Help: `openclaw --help`
- Check Status: `openclaw status`
- View Logs: Check client app logs tab
- **Required:** Configure with an LLM API key (OpenAI, Anthropic, etc.) during `openclaw onboard`

## Quick Start Checklist

### Setup (One-Time)
- [ ] Install OpenClaw: `npm install -g openclaw@latest`
- [ ] Initialize daemon: `openclaw onboard --install-daemon`
- [ ] **Configure with LLM API key** (OpenAI/Anthropic/etc.)
- [ ] Download OpenClaw client from link above
- [ ] Run client and paste OpenHome API key
- [ ] Verify "Connected" status and "welcome" message

### Template Usage
- [ ] Get template from OpenHome dashboard or GitHub
- [ ] Define your trigger words in `config.json`
- [ ] Customize `first_function()` for your use case
- [ ] Add command validation and safety checks
- [ ] Test with safe commands first
- [ ] Add error handling and timeouts
- [ ] Deploy your custom ability!

## Support & Contribution

If you build something cool with this template:
- 🎉 Share it with the OpenHome community
- 💡 Contribute improvements back to the template
- 🤝 Help others troubleshoot in community forums
- 📝 Document your use case for future builders

## Final Reminder

⚠️ **This template is a foundation, not a finished product.**

The power of OpenClaw integration comes from YOUR customization:
- Define specific trigger words
- Implement domain-specific logic
- Add safety validations
- Create multi-step workflows
- Build something unique!

Don't just deploy the template as-is — make it yours! 🚀
