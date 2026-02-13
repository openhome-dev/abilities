# Getting Started — Your First Ability in 5 Minutes

This guide walks you through building, testing, and uploading a custom Ability to OpenHome.

---

## What You'll Need

- An OpenHome account at [app.openhome.com](https://app.openhome.com)
- A text editor
- Basic Python knowledge

---

## Step 1: Grab a Template

Clone this repo (or download just the template folder):

```bash
git clone https://github.com/openhome-dev/abilities.git
cp -r abilities/templates/basic-template my-ability
cd my-ability
```

You now have one file to edit: `main.py`.

---

## Step 2: Write Your Logic

Edit `main.py`. The template gives you a working starting point. Here's what you can customize:

```python
async def run(self):
    # Greet the user
    await self.capability_worker.speak("Hello! What can I do for you?")

    # Listen for input
    user_input = await self.capability_worker.user_response()

    # Do something with it (call an API, use the LLM, etc.)
    response = self.capability_worker.text_to_text_response(
        f"Help the user with: {user_input}"
    )

    # Speak the result
    await self.capability_worker.speak(response)

    # IMPORTANT: Always call this when done
    self.capability_worker.resume_normal_flow()
```

> **Note:** The `register_capability` method in the template is required boilerplate — copy it exactly. The platform handles `config.json` automatically at runtime; you never need to create or edit it.

See [patterns.md](patterns.md) for more examples — API calls, loops, audio playback, etc.

---

## Step 3: Zip and Upload

1. Zip your `main.py` (or the whole folder)
2. Go to [app.openhome.com](https://app.openhome.com)
3. Navigate to **Abilities** → **Add Custom Ability**
4. Upload your `.zip` file
5. Fill in the name and description
6. Set your **trigger words** — the phrases that will activate your Ability

---

## Step 4: Test in the Live Editor

After uploading, click **Live Editor** on your Ability. Here you can:

- Edit files directly in the browser
- Click **Start Live Test** to test your Ability
- Check trigger words
- View logs in real time
- Commit changes when satisfied

---

## Step 5: Trigger It

Start a conversation with any Personality. Say one of your trigger phrases, and your Ability will activate.

---

## What's Next?

- **Want to share it?** See [Contributing](../CONTRIBUTING.md) to submit it to this repo
- **Want to publish it?** See [Publishing to Marketplace](publishing-to-marketplace.md)
- **Need more SDK functions?** See [CapabilityWorker API Reference](capability-worker-api.md)
- **Full SDK reference?** See [OpenHome Ability SDK — Complete Reference](https://github.com/openhome-dev/abilities/blob/dev/docs/OpenHome_SDK_Reference.md)
- **Looking for patterns?** See [Patterns Cookbook](patterns.md)
