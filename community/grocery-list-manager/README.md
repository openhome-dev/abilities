
# Grocery List Manager

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@engrumair842--arch-lightgrey?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10+-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

> Voice-controlled grocery list manager for hands-free shopping list management.

---

## 📖 What It Does

Grocery List Manager is a voice-first shopping list ability that lets you add, remove, read, and clear grocery items using natural language commands. Perfect for when your hands are busy cooking, cleaning, or shopping.

**Key Features:**
- 🎤 **Voice-Controlled** - Completely hands-free operation
- 🧠 **Natural Language** - Understands casual speech ("add milk and eggs")
- 📝 **Smart Parsing** - LLM extracts items from your sentences
- 🔄 **Multi-Item Support** - Add/remove multiple items at once
- 🚫 **Easy Exit** - Say "stop", "quit", or "done" anytime

---

## 🎤 Suggested Trigger Words

Activate the ability by saying:

- `"grocery list"`
- `"shopping list"`
- `"manage groceries"`
- `"my list"`

*(Configure trigger words in the OpenHome dashboard)*

---

## 🚀 How to Use

### Basic Commands

| Command | What to Say | What Happens |
|---------|-------------|--------------|
| **Add** | "Add milk", "Put eggs and butter on the list" | Adds items to your list |
| **Remove** | "Remove milk", "Delete eggs" | Removes items from your list |
| **Read** | "What's on my list?", "Read my list" | Reads your list aloud |
| **Clear** | "Clear list", "Delete everything" | Clears all items |
| **Exit** | "Stop", "Quit", "Done" | Exits the ability |

---

## 💬 Example Conversations

### **Adding Items**

```

- **Issues:** Open an issue on GitHub
- **Discord:** [OpenHome Discord](https://discord.gg/openhome)
- **Docs:** [OpenHome Documentation](https://docs.openhome.com)

---

**Made with ❤️ for the OpenHome community**

*Voice-first grocery management, because your hands should be free to cook, not to write lists.*

You: "Grocery list"
Assistant: "Grocery list ready. Say add, remove, read, or clear."

You: "Add milk, eggs, and bread"
Assistant: "Added 3 items."

You: "Put butter on the list"
Assistant: "Added butter."
```

### **Reading the List**

```
You: "What's on my list?"
Assistant: "You have 4 items: milk, eggs, bread, butter."
```

### **Removing Items**

```
You: "Remove milk"
Assistant: "Removed milk."

You: "Delete eggs and bread"
Assistant: "Removed 2 items."
```

### **Clearing the List**

```
You: "Clear the list"
Assistant: "Cleared 1 items."

You: "What's on my list?"
Assistant: "Your list is empty."
```

### **Exiting**

```
You: "Done"
Assistant: "List saved. Goodbye!"
```

---

## 🛠️ Setup

### Installation

1. **Upload to OpenHome:**
   - Go to [app.openhome.com](https://app.openhome.com)
   - Navigate to "My Abilities"
   - Click "Add Custom Ability"
   - Upload the ability files

2. **Configure Trigger Words:**
   - Set your preferred trigger words in the dashboard
   - Suggested: "grocery list", "shopping list"

3. **Test:**
   - Use "Start Live Test" in the ability editor
   - Try adding, removing, and reading items
   - Verify all exit words work

### Requirements

- No external APIs required
- No API keys needed
- Works entirely with OpenHome's built-in LLM

---

## 🏗️ How It Works

### Architecture

```
User Voice Input
      ↓
Intent Classification (LLM)
      ↓
┌─────────┬─────────┬─────────┬─────────┐
│   Add   │ Remove  │  Read   │  Clear  │
└─────────┴─────────┴─────────┴─────────┘
      ↓
Item Extraction (LLM)
      ↓
List Operation
      ↓
Voice Feedback
```

### Intent Classification

The ability uses OpenHome's LLM to classify user intent into:
- **add** - Adding items to the list
- **remove** - Removing items from the list
- **read** - Reading the list aloud
- **clear** - Clearing all items
- **unknown** - Unclear intent

### Item Extraction

For add/remove operations, the LLM extracts item names from natural language:
- "add milk and eggs" → `["milk", "eggs"]`
- "put bread on the list" → `["bread"]`
- "I need butter, cheese, yogurt" → `["butter", "cheese", "yogurt"]`

### Voice Optimization

**Short Responses:**
- ✅ "Added milk." (2 words)
- ✅ "Added 3 items." (3 words)
- ❌ NOT: "I have successfully added milk to your grocery list." (10 words)

**Smart List Reading:**
- **1-5 items:** Reads all items
- **6+ items:** Reads count + first 3 items (avoids long lists)

---

## 🎨 Voice Design Principles

### 1. **Brevity**
All responses are ≤2 sentences and optimized for listening:
- "Added milk." (not "I've added milk to your list")
- "You have 4 items: milk, eggs, bread, butter." (clear and concise)

### 2. **Natural Language**
Understands casual speech patterns:
- "Add milk" ✅
- "Put milk on the list" ✅
- "I need milk" ✅

### 3. **Flexible Exit**
Supports 6 exit words for user convenience:
- stop, exit, quit, done, cancel, goodbye

### 4. **Error Tolerance**
Handles unclear input gracefully:
- Empty responses → "I didn't catch that."
- Unknown items → "I couldn't find any items."
- Item not in list → "Item not found."

---

## 🔧 Technical Details

### SDK Methods Used

| Method | Usage | Purpose |
|--------|-------|---------|
| `speak()` | Voice output | Speak responses to user |
| `user_response()` | Voice input | Listen for user commands |
| `text_to_text_response()` | LLM processing | Intent classification & item extraction |
| `resume_normal_flow()` | Exit control | Return control to OpenHome |

### State Management

```python
grocery_list: list = []  # Session-scoped list
# Resets each time ability is triggered
# No persistent storage (privacy-friendly)
```

### Error Handling

```python
try:
    # Main loop
except Exception as e:
    # Log error
    # Graceful exit message
finally:
    # ALWAYS return control
    resume_normal_flow()
```

---

## 📊 Performance

### Response Times

| Operation | Expected Time | Voice-Friendly? |
|-----------|---------------|-----------------|
| Add items | 1-2 seconds | ✅ Yes |
| Remove items | 1-2 seconds | ✅ Yes |
| Read list | <1 second | ✅ Yes |
| Clear list | <1 second | ✅ Yes |
| Exit | <1 second | ✅ Yes |

### Scalability

- **Recommended:** 1-20 items per list
- **Maximum:** No hard limit, but voice reading is capped at first 3 items for lists >5

---

## 🎯 Use Cases

### **While Cooking**
```
You: "Grocery list"
You: "Add flour, sugar, and vanilla extract"
Assistant: "Added 3 items."
```

### **Weekly Planning**
```
You: "Grocery list"
You: "Add chicken, rice, broccoli, carrots, onions"
Assistant: "Added 5 items."
You: "What's on my list?"
Assistant: "You have 5 items: chicken, rice, broccoli, carrots, onions."
```

### **Shopping Mode**
```
You: "Grocery list"
You: "What's on my list?"
Assistant: "You have 8 items. First three: milk, eggs, bread."
You: "Remove milk"
Assistant: "Removed milk."
```

---

## 🚫 Limitations

### Current Limitations

1. **No Persistence**
   - List resets each session
   - Cannot save lists between uses
   - Future: Add persistent storage

2. **No Quantities**
   - "Add 2 gallons of milk" stores as "milk"
   - Future: Parse and store quantities

3. **No Categories**
   - All items in one flat list
   - Future: Auto-categorize (dairy, produce, etc.)

4. **Session-Only**
   - List cleared when ability exits
   - Future: Multi-session support

### Known Issues

- **Duplicate items:** Currently allows duplicates
- **Long lists:** Reading 20+ items can be tedious (automatically summarized)

---

## 🔮 Future Enhancements

### Planned Features

**Phase 1: Persistence**
- [ ] Save lists between sessions
- [ ] Multiple named lists (e.g., "weekly", "party")
- [ ] List history

**Phase 2: Smart Features**
- [ ] Quantity parsing ("2 gallons of milk")
- [ ] Auto-categorization (produce, dairy, meat)
- [ ] Smart suggestions based on history

**Phase 3: Integration**
- [ ] Email list to yourself
- [ ] Share via text message
- [ ] Export to common apps (Instacart, Amazon Fresh)

---

## 🐛 Troubleshooting

### Common Issues

**Issue: Items not being added**
```
Solution: Speak clearly and use simple item names
Good: "Add milk"
Bad: "Add that organic 2% milk from the store"
```

**Issue: Can't exit the ability**
```
Solution: Say one of the exit words clearly:
"stop", "quit", "done", "exit", "cancel", "goodbye"
```

**Issue: Wrong items detected**
```
Solution: Be specific and pause between items
Good: "Add milk... eggs... and bread"
Bad: "Add milk eggs bread" (too fast)
```

**Issue: List reads too many items**
```
Solution: Keep lists under 20 items for best voice experience
Or use: "What's on my list?" (auto-summarizes long lists)
```

---

## 📝 Code Structure

### File Organization

```
grocery-list-manager/
├── main.py          # Main ability code
├── __init__.py      # Package initialization
├── README.md        # This file
└── config.json      # Auto-generated by OpenHome (don't create manually)
```

### Class Structure

```python
GroceryListManagerCapability
├── register_capability()  # OpenHome registration
├── call()                 # Entry point
├── run()                  # Main loop
├── _classify_intent()     # LLM intent detection
├── _add_items()          # Add operation
├── _remove_items()       # Remove operation
├── _read_list()          # Read operation
└── _clear_list()         # Clear operation
```

---

## 🤝 Contributing

Found a bug or have a feature idea? Contributions welcome!

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

## 📄 License

MIT License - See LICENSE file for details

---

## 👤 Author

**engrumair842-arch**
- GitHub: [@engrumair842-arch](https://github.com/engrumair842-arch)
- Created: February 2026

---

## 🙏 Acknowledgments

- OpenHome team for the excellent SDK
- Community for feedback and testing
- LLM for natural language understanding

---

## 📞 Support

- **Issues:** Open an issue on GitHub
- **Discord:** [OpenHome Discord](https://discord.gg/openhome)
- **Docs:** [OpenHome Documentation](https://docs.openhome.com)

---

**Made with ❤️ for the OpenHome community**

*Voice-first grocery management, because your hands should be free to cook, not to write lists.*