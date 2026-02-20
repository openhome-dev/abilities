# OpenHome Local Link - Mac Terminal Control Template
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Template](https://img.shields.io/badge/Type-Template-blue?style=flat-square)

## What This Is
**This is a template ability** that connects OpenHome to your Mac terminal. Use voice commands to run terminal commands, check system status, manage files, and automate Mac workflows — all without OpenClaw.

## What You Can Build
Examples of abilities you could create with this template:
- Mac system monitor (disk space, CPU, memory)
- File management assistant (create, move, delete files)
- Development environment controller (git commands, npm scripts)
- Application launcher (open/close Mac apps)
- Network diagnostics tool (ping, traceroute, speed test)
- Automation scripts (backup files, cleanup temp folders)

## Template Trigger Words
This template uses generic triggers - **customize these** for your specific ability:
- Any Mac terminal command request
- Configure your own trigger words in `config.json`

## Requirements

### 1. Download Local Client
**[Download local_client.py](https://drive.google.com/file/d/12Is4eXchH5dDjlG39Knp4oRuD-V3D-v_/view?usp=drive_link)**

This Python script runs on your Mac and receives commands from OpenHome.

### 2. Python 3.7+
Verify you have Python installed:
```bash
python3 --version
```

### 3. OpenHome API Key
Get your API key from [OpenHome Dashboard → Settings → API Keys](https://app.openhome.com/dashboard/settings)

## Setup Instructions

### Step 1: Download and Configure Client

1. **Download the client:**
   - Click the [download link](https://drive.google.com/file/d/12Is4eXchH5dDjlG39Knp4oRuD-V3D-v_/view?usp=drive_link)
   - Save `local_client.py` to a convenient location (e.g., `~/openhome/`)

2. **Open the client file:**
   ```bash
   cd ~/openhome/
   nano local_client.py  # or use any text editor
   ```

3. **Add your OpenHome API Key:**
   - Find the line: `OPENHOME_API_KEY = "your_api_key_here"`
   - Replace with: `OPENHOME_API_KEY = "YOUR_ACTUAL_KEY"`
   - Save and exit

### Step 2: Run the Client

1. **Make the client executable (optional):**
   ```bash
   chmod +x local_client.py
   ```

2. **Run the client:**
   ```bash
   python3 local_client.py
   ```

3. **Verify connection:**
   - You should see: `Connected to OpenHome` or similar message
   - Keep this terminal window open while using the ability

**Pro tip:** Run the client in the background or use a terminal multiplexer like `tmux`:
```bash
# Using tmux (recommended for persistent sessions)
tmux new -s openhome
python3 local_client.py
# Press Ctrl+B then D to detach

# Or run in background
nohup python3 local_client.py > /tmp/openhome_client.log 2>&1 &
```

### Step 3: Get the Template Ability

1. Find **OpenHome Local Link** template from:
   - OpenHome Dashboard abilities library, OR
   - [GitHub Repository](https://github.com/OpenHome)

2. Add to your OpenHome Personality

3. The template is ready to test immediately!

## Using This Template

### Default Template Behavior
The unmodified template:
1. Listens for Mac-related voice commands
2. Converts natural language → terminal commands using LLM
3. Sends command to your local client via `exec_local_command()`
4. Client executes the command on your Mac terminal
5. Response is sent back to OpenHome
6. LLM converts technical output → natural spoken response

### Testing the Template
> **User:** "list all files"  
> **AI:** "Running command: ls -la"  
> *(Command executes on your Mac)*  
> **AI:** "I found 15 files in your current directory including Documents, Downloads, and Desktop."

---

> **User:** "show current directory"  
> **AI:** "Running command: pwd"  
> **AI:** "You're currently in /Users/yourname/Documents"

---

> **User:** "check disk space"  
> **AI:** "Running command: df -h"  
> **AI:** "Your main drive has 150 GB free out of 500 GB total."

## Core Template Function

### `exec_local_command()`
Sends a command to your local Mac terminal and returns the response.

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
- `command` (str | dict): **Required.** Terminal command to execute
- `target_id` (str | None): **Optional.** Device identifier (default: "laptop")
- `timeout` (float): **Optional.** Max seconds to wait (default: 10.0)

**Template Usage:**
```python
# Basic usage (as shown in template)
response = await self.capability_worker.exec_local_command(terminal_command)

# With custom timeout for long commands
response = await self.capability_worker.exec_local_command(
    "find / -name '*.log'",
    timeout=30.0
)

# With specific target device
response = await self.capability_worker.exec_local_command(
    "df -h",
    target_id="laptop"
)
```

## How the Template Works

### 1. Voice Input → Natural Language
User speaks: "list all files in my downloads folder"

### 2. LLM Converts to Terminal Command
System prompt guides LLM to generate Mac-compatible commands:
```python
system_prompt = """
You are a Mac terminal command generator.
Rules:
- Respond ONLY with the terminal command
- Use macOS-compatible commands (zsh/bash)
- No explanations, quotes, or markdown
- Avoid sudo unless necessary
"""
```

Result: `ls -la ~/Downloads`

### 3. Command Sent to Local Client
```python
response = await self.capability_worker.exec_local_command(terminal_command)
```

### 4. Client Executes on Mac
The `local_client.py` runs the command in your Mac terminal and captures output.

### 5. Response Formatted for Speech
LLM converts technical output to conversational language:
```python
check_response_system_prompt = """
Tell if the command was successful in easier terms.
If user wanted information, return that information.
"""
```

### 6. AI Speaks Result
"I found 47 files in your Downloads folder including PDFs, images, and documents."

## Customizing the Template

### 1. Modify System Prompt
Change how commands are generated:

```python
def get_system_prompt(self):
    return """
    You are a Mac automation assistant specialized in [YOUR DOMAIN].
    
    Rules:
    - [Your custom rules]
    - [Specific command patterns]
    
    Examples:
    User: "[your example]" -> [your command]
    """
```

### 2. Add Pre-Processing Logic
Validate or transform commands before execution:

```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    # ⬇️ ADD YOUR VALIDATION HERE
    if "delete" in user_inquiry.lower() or "rm -rf" in user_inquiry.lower():
        await self.capability_worker.speak("I can't run destructive commands for safety.")
        self.capability_worker.resume_normal_flow()
        return
    # ⬆️
    
    # ... rest of template
```

### 3. Add Confirmation for Dangerous Commands
```python
terminal_command = self.capability_worker.text_to_text_response(...)

# ⬇️ ADD CONFIRMATION LOGIC
if any(danger in terminal_command for danger in ["rm", "sudo", "shutdown"]):
    await self.capability_worker.speak(f"This command will {terminal_command}. Confirm?")
    confirmation = await self.capability_worker.user_response()
    if "yes" not in confirmation.lower():
        await self.capability_worker.speak("Cancelled.")
        self.capability_worker.resume_normal_flow()
        return
# ⬆️

response = await self.capability_worker.exec_local_command(terminal_command)
```

### 4. Chain Multiple Commands
```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    # Example: "backup my documents"
    if "backup" in user_inquiry.lower():
        commands = [
            "mkdir -p ~/Backups",
            "cp -r ~/Documents ~/Backups/Documents_$(date +%Y%m%d)",
            "echo 'Backup complete'"
        ]
        
        for cmd in commands:
            await self.capability_worker.speak(f"Running: {cmd}")
            response = await self.capability_worker.exec_local_command(cmd)
            
        await self.capability_worker.speak("Backup completed successfully!")
        self.capability_worker.resume_normal_flow()
        return
    
    # ... rest of template for other commands
```

## Example Abilities You Can Build

### 1. Git Assistant
```python
def get_system_prompt(self):
    return """
    Convert git operations to commands.
    
    Examples:
    "check git status" -> git status
    "commit changes" -> git add . && git commit -m "Update"
    "push to main" -> git push origin main
    "create branch feature-x" -> git checkout -b feature-x
    """
```

### 2. System Monitor
```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    if "system health" in user_inquiry.lower():
        metrics = {
            "CPU": "top -l 1 | grep 'CPU usage'",
            "Memory": "vm_stat | head -n 10",
            "Disk": "df -h /",
            "Battery": "pmset -g batt"
        }
        
        report = []
        for name, cmd in metrics.items():
            response = await self.capability_worker.exec_local_command(cmd)
            # Parse and format response
            report.append(f"{name}: {response}")
        
        await self.capability_worker.speak(". ".join(report))
        self.capability_worker.resume_normal_flow()
        return
```

### 3. Development Environment Setup
```python
async def first_function(self):
    user_inquiry = await self.capability_worker.wait_for_complete_transcription()
    
    if "start dev environment" in user_inquiry.lower():
        await self.capability_worker.speak("Starting development environment...")
        
        commands = [
            "cd ~/Projects/my-app",
            "code .",  # Opens VS Code
            "npm run dev &",  # Starts dev server in background
            "open http://localhost:3000"  # Opens browser
        ]
        
        for cmd in commands:
            await self.capability_worker.exec_local_command(cmd, timeout=15.0)
        
        await self.capability_worker.speak("Development environment is ready!")
        self.capability_worker.resume_normal_flow()
        return
```

### 4. File Organization Assistant
```python
def get_system_prompt(self):
    return """
    File management commands for Mac.
    
    Examples:
    "organize downloads by type" -> 
    mkdir ~/Downloads/Images ~/Downloads/Documents ~/Downloads/Videos &&
    mv ~/Downloads/*.jpg ~/Downloads/Images/ 2>/dev/null || true &&
    mv ~/Downloads/*.pdf ~/Downloads/Documents/ 2>/dev/null || true
    
    "clean up temp files" -> rm -rf ~/Library/Caches/Homebrew/*
    "find large files" -> find ~ -type f -size +100M
    """
```

## Modifying the Local Client

The `local_client.py` file can be customized to:

### Add Custom Command Handlers
```python
# In local_client.py
def execute_command(command):
    # Add special handling for specific commands
    if command == "get_battery":
        result = subprocess.run(['pmset', '-g', 'batt'], capture_output=True)
        return parse_battery_output(result.stdout)
    
    # Default: run command as-is
    result = subprocess.run(command, shell=True, capture_output=True)
    return result.stdout.decode()
```

### Add Logging
```python
# In local_client.py
import logging

logging.basicConfig(filename='openhome_commands.log', level=logging.INFO)

def execute_command(command):
    logging.info(f"Executing: {command}")
    result = subprocess.run(command, shell=True, capture_output=True)
    logging.info(f"Result: {result.stdout[:100]}...")
    return result.stdout.decode()
```

### Add Security Restrictions
```python
# In local_client.py
BLOCKED_COMMANDS = ['rm -rf /', 'sudo', 'format', 'dd if=']

def execute_command(command):
    if any(blocked in command for blocked in BLOCKED_COMMANDS):
        return "ERROR: Blocked command for safety"
    
    result = subprocess.run(command, shell=True, capture_output=True)
    return result.stdout.decode()
```

## Best Practices

### 1. Always Test Commands Manually First
Before automating with voice:
```bash
# Test the command in your terminal first
ls -la ~/Documents

# Verify it does what you expect
# Then add to your ability
```

### 2. Use Safe Defaults
```python
# Avoid destructive operations by default
SAFE_COMMANDS = ['ls', 'pwd', 'cd', 'cat', 'grep', 'find', 'df', 'du']

if not any(safe in terminal_command for safe in SAFE_COMMANDS):
    await self.capability_worker.speak("This command needs confirmation.")
    # ... confirmation logic
```

### 3. Handle Timeouts Appropriately
```python
# Quick commands (default 10s)
response = await self.capability_worker.exec_local_command("pwd")

# Long-running commands (increase timeout)
response = await self.capability_worker.exec_local_command(
    "find / -name '*.log'",
    timeout=60.0
)
```

### 4. Add Error Handling
```python
try:
    response = await self.capability_worker.exec_local_command(terminal_command)
    
    if "error" in response.lower() or "permission denied" in response.lower():
        await self.capability_worker.speak("That command failed. Try a different approach?")
    else:
        # Process successful response
        ...
        
except asyncio.TimeoutError:
    await self.capability_worker.speak("That took too long. It might still be running.")
except Exception as e:
    self.worker.editor_logging_handler.error(f"Command failed: {e}")
    await self.capability_worker.speak("Something went wrong.")
finally:
    self.capability_worker.resume_normal_flow()
```

## Troubleshooting

### Client Won't Connect
**Problem:** `local_client.py` shows connection error

**Solutions:**
1. Verify API key is correct (from Dashboard → Settings → API Keys)
2. Check Python version: `python3 --version` (needs 3.7+)
3. Check internet connection
4. Look for firewall blocking Python connections

### Commands Not Executing
**Problem:** Client connected but commands fail

**Solutions:**
1. Check client terminal for error messages
2. Verify command works when run manually in terminal
3. Check client logs: `tail -f /tmp/openhome_client.log`
4. Restart the client: `pkill -f local_client.py && python3 local_client.py`

### Permission Errors
**Problem:** Commands fail with "Permission denied"

**Solutions:**
1. Some commands require admin privileges
2. Modify client to use `sudo` (with password handling)
3. Run client with appropriate permissions
4. Avoid commands that need root access

### Client Disconnects Randomly
**Problem:** Client connection drops after a while

**Solutions:**
1. Use `tmux` to keep session alive:
   ```bash
   tmux new -s openhome
   python3 local_client.py
   # Ctrl+B then D to detach
   ```
2. Add auto-reconnect logic to client
3. Check for Mac sleep settings interfering

### Response Formatting Issues
**Problem:** AI speaks raw terminal output

**Solutions:**
1. The template formats responses automatically via LLM
2. Check `check_response_system_prompt` is correct
3. Add custom parsing for specific commands
4. Modify the system prompt to guide better responses

## Security Considerations

### ⚠️ Important Security Notes
- **This runs real terminal commands** on your Mac with your user permissions
- **No sandbox protection** — commands execute exactly as typed
- **Anyone with access to your OpenHome** can run commands via your client
- **Protect your API key** — don't share or commit to public repos

### Recommended Safety Measures

**1. Command Whitelist**
```python
ALLOWED_COMMANDS = ['ls', 'pwd', 'df', 'du', 'cat', 'grep', 'find']

if not any(cmd in terminal_command for cmd in ALLOWED_COMMANDS):
    await self.capability_worker.speak("That command is not allowed.")
    return
```

**2. Confirmation for Destructive Actions**
Always confirm before running:
- `rm` (delete)
- `sudo` (admin)
- `shutdown` / `reboot`
- `dd` (disk operations)
- `format` / `diskutil`

**3. Separate User for Client**
Run the client under a limited user account:
```bash
# Create a new user for OpenHome
sudo dscl . -create /Users/openhome
sudo dscl . -create /Users/openhome UserShell /bin/bash
sudo dscl . -create /Users/openhome RealName "OpenHome Client"

# Run client as that user
su openhome -c "python3 local_client.py"
```

**4. Monitor Client Logs**
```bash
# Check what commands were run
grep "Executing:" /tmp/openhome_client.log

# Set up alerts for dangerous commands
tail -f /tmp/openhome_client.log | grep -E "rm|sudo|shutdown"
```

## Technical Architecture
```
Voice Input → OpenHome Ability → exec_local_command()
                                        ↓
                                  local_client.py
                                  (WebSocket connection)
                                        ↓
                                  Mac Terminal Execution
                                  (subprocess.run)
                                        ↓
                        Response ← AI Formatting ← Template
```

## Comparison: Local Link vs OpenClaw

| Feature | Local Link | OpenClaw |
|---------|-----------|----------|
| **Setup** | Single Python file | Full CLI + daemon + LLM config |
| **Dependencies** | Python 3.7+ only | Node.js + npm + LLM API key |
| **Complexity** | Simple, minimal | Advanced, feature-rich |
| **Customization** | Direct Python editing | MCP server integration |
| **Use Case** | Quick terminal access | Complex automation workflows |
| **Best For** | Simple commands, prototyping | Production automation |

Use **Local Link** when you want simple, direct terminal access.  
Use **OpenClaw** when you need robust automation with LLM-powered intelligence.

## Quick Start Checklist

### Setup (One-Time)
- [ ] Download `local_client.py` from Google Drive
- [ ] Add OpenHome API key to client file
- [ ] Test client connection: `python3 local_client.py`
- [ ] Verify "Connected" message

### Template Usage
- [ ] Get template from OpenHome dashboard
- [ ] Test with safe command: "show current directory"
- [ ] Verify response is spoken correctly
- [ ] Customize system prompt for your use case
- [ ] Add safety validations
- [ ] Define custom trigger words in `config.json`

## Links & Resources

**Required Downloads:**
- **[local_client.py](https://drive.google.com/file/d/12Is4eXchH5dDjlG39Knp4oRuD-V3D-v_/view?usp=drive_link)** — Download this file (required)

**OpenHome:**
- [Dashboard](https://app.openhome.com/dashboard)
- [API Key Management](https://app.openhome.com/dashboard/settings) — Get your API key here
- [Abilities Library](https://app.openhome.com/dashboard/abilities)

**Mac Terminal Resources:**
- macOS Terminal User Guide
- `man` command for documentation (e.g., `man ls`)
- Homebrew for package management

## Support & Contribution

If you build something cool with this template:
- 🎉 Share it with the OpenHome community
- 💡 Contribute improvements to the template
- 🤝 Help others in community forums
- 📝 Document your use case

## Final Reminder

⚠️ **This template is a starting point, not a finished product.**

The power comes from YOUR customization:
- Define specific commands for your workflow
- Add safety validations
- Create domain-specific assistants
- Build something unique for your Mac!

**Don't deploy the template as-is — make it yours!** 🚀
