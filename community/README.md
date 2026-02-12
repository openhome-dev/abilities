# Community Abilities

This folder contains Abilities contributed by the OpenHome community.

> **Note:** These Abilities are community-maintained and are not officially supported by OpenHome.
> For official Abilities, see [`official/`](../official/).

---

## How to Contribute

1. **Copy a template** from `templates/` into this folder:

   ```bash
   cp -r templates/basic-template community/your-ability-name
   ```

2. **Build your Ability** — edit `main.py`, add a `README.md`

3. **Test it** in the [OpenHome Live Editor](https://app.openhome.com/dashboard/abilities)

4. **Submit a Pull Request** against the `dev` branch

See [**CONTRIBUTING.md**](../CONTRIBUTING.md) for the full guide.

---

## Folder Structure

Each community Ability should follow this structure:

```
community/
└── your-ability-name/
    ├── main.py          # Your Ability code
    └── README.md        # Description, trigger words, setup instructions
```

---

## Quick Checklist

Before submitting, make sure your Ability:

- [ ] Extends `MatchingCapability`
- [ ] Includes `register_capability()` boilerplate
- [ ] Calls `resume_normal_flow()` on every exit path
- [ ] Has no `print()` statements (use `editor_logging_handler`)
- [ ] Has no hardcoded API keys
- [ ] All `requests.*()` calls include a `timeout` parameter
- [ ] Includes a `README.md` with description and suggested trigger words
- [ ] PR targets the **`dev`** branch

---

## Community Guidelines

- **Be respectful** in PR reviews and issue discussions
- **Don't modify** other contributors' Abilities without their consent
- **Report bugs** via [GitHub Issues](https://github.com/openhome-dev/abilities/issues)
- **Suggest ideas** via [Ability Ideas](https://github.com/openhome-dev/abilities/discussions/categories/ability-ideas)

---

## Promotion to Official

Outstanding community Abilities can be promoted to the `official/` folder. See the [Promotion Path](../CONTRIBUTING.md#promotion-path) section in CONTRIBUTING.md for criteria.
