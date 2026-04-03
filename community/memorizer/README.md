# Personality Preferences Capability

## What does this Ability do?

Continuously maintains and updates `user_preferences.md`, which is injected into other prompts to dynamically adjust the assistant's personality and behavior.

This capability listens for user preferences, extracts structured facts, normalizes them, and rewrites `user_preferences.md`. Because this file is injected into other prompts, **personality prompts update automatically whenever preferences change**.

This creates a persistent, evolving personality system without modifying prompts directly.

---

## Key Behavior

* Extracts preferences from natural language
* Normalizes and deduplicates preferences
* Replaces conflicting preferences intelligently
* Persists preferences in `user_preferences.md`
* Continuously updates the file
* Allows other prompts to inject preferences dynamically

---

## Example Behavior

User says:

```
I'm vegetarian and prefer short responses
```

`user_preferences.md` becomes:

```markdown
# User Preferences

- Vegetarian
- Prefers short responses
```

Other prompts inject:

```
{{inject:user_preferences.md}}
```

Assistant behavior updates automatically.

---

## Supported Actions

### ADD

Adds new preferences from user input

Examples:

```
Remember that I'm vegetarian
I prefer short responses
Update my profile: I like technical explanations
```

---

### DELETE

Removes existing preferences

Examples:

```
Forget that I'm vegetarian
Remove my communication preferences
```

---

### REVIEW

Lists stored preferences

Examples:

```
What do you know about me?
List my preferences
What have I told you?
```

---

## Smart Features

### Conflict Resolution

Automatically replaces conflicting preferences:

```
Prefers short responses
→ replaced by →
Prefers detailed responses
```

---

### Compound Preference Splitting

Input:

```
I'm vegetarian and 20 years old
```

Stored as:

```
- Vegetarian
- 20 years old
```

---

### Deduplication

Automatically removes duplicates:

```
Vegetarian
I'm vegetarian
vegetarian
```

Stored as:

```
- Vegetarian
```

---

## File Format

`user_preferences.md`

```markdown
# User Preferences

- Preference 1
- Preference 2
- Preference 3
```

---

## Architecture

```
User Input
    ↓
Preference Extraction
    ↓
Normalization
    ↓
Merge / Overwrite Logic
    ↓
Write user_preferences.md
    ↓
Prompt Injection
    ↓
Updated Personality Behavior
```

---

## Key Design Principle

This capability **does not modify prompts directly**.

Instead:

* Updates `user_preferences.md`
* Other prompts inject the file
* Personality updates propagate automatically

This keeps personality **modular and data-driven**.

---

## Type

* New capability
* Personality / prompt infrastructure
* Persistent user preference manager

---

## External Dependencies

* No external APIs
* Uses internal `CapabilityWorker` file storage

---

## Testing

* Tested preference extraction
* Tested overwrite behavior
* Tested deletion logic
* Tested normalization of compound preferences
* Tested persistence across sessions

---

## Checklist

* Extends `MatchingCapability`
* Uses `CapabilityWorker` for file storage
* Updates `user_preferences.md`
* Calls `resume_normal_flow()` on exit
* No external API dependencies
* No hardcoded values
* Handles compound preferences
* Handles overwrite logic
* Deduplicates entries

---

## Anything else?

This capability functions as **personality infrastructure** for the agent.

Other prompts should inject:

```
{{inject:user_preferences.md}}
```

This ensures personality prompts **continuously update automatically** as preferences evolve.
