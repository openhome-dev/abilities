# OpenBrain

A deterministic answer layer for the exact-answer class. On a trigger phrase the
transcript goes straight to the DevKit, which answers with pattern-and-table code.
This ability never calls a model. OpenHome supplies the transcript, the speech and the
agent session. When the engine has no exact answer it returns nothing and the turn goes
back to the configured agent, so the ability is silent rather than wrong.

**This ability requires a connected DevKit.** Its category is `local`. The compiled
engine is installed on the device from `requirements.txt`; without a device there is
nothing to call.

## Relationship to `community/astral`

`community/astral` is version one: a single self-contained `main.py` with the engine
generated inline, which runs for any agent with no device and no dependency. It stays
as it was accepted in PR #361.

This directory is version two. The engine moved out of the ability and into a compiled
package, so what OpenHome runs is a short readable shim and the answers come from a
versioned dependency pinned by hash. The two can coexist; they are not upgrades of each
other, they are the cloud path and the device path.

## Answers on the device

Time and date, arithmetic, money and unit conversions, grades, chemistry, physics,
statistics and number tools. The shim also reads DevKit telemetry and can publish
supported MQTT device commands. With the Astral local hub installed it additionally
reaches the library, definitions, timers, notes and native mathematics on the card.

| Example | Deterministic answer |
|---|---|
| What is twenty percent of eighty? | 20 percent of 80 is 16. |
| Convert ten pounds to kilograms. | 10 pounds is 4.54 kilograms. |
| How many feet in a mile? | 1 mile is 5280 feet. |
| Molar mass of water. | The molar mass of water (H2O) is 18.015 grams per mole. |
| Standard deviation of 4 6 8 10. | The sample standard deviation of 4, 6, 8, 10 is 2.58, around a mean of 7. |
| Is 91 prime? | No, 91 isn't prime. It's 7 times 13. |

A computed answer and a correctly transcribed spoken request are separate requirements.
Fast arithmetic does not establish end-to-end voice latency or transcription accuracy.

## The dependency

`requirements.txt` names `astral-kernel`, a compiled package built for CPython 3.13 on
Linux aarch64, which is what a DevKit runs. It is pinned to a release asset by SHA-256,
so pip verifies the hash on install. A compiled wheel is specific to an interpreter and
an architecture; that is a property of compiled code rather than a defect.

The integration files in this directory are MIT. `astral-kernel` is proprietary and
separately licensed. Nothing is obfuscated and there is no binary in this package: there
is a named dependency, and [BOUNDARY.md](BOUNDARY.md) says exactly what it does and
where the seam is.

Version 2.2.7 is installed and verified on the author's device. Releases are on the
[releases page](https://github.com/Jmesmykil/astral-OpenBrain/releases), and the
[release procedure](https://github.com/Jmesmykil/astral-OpenBrain/blob/main/RELEASE.md)
records how each one is built and checked.

## Checking an installation

The shim is directly callable, which is how to verify a device without speaking to it:

```sh
python3 devkit_functions.py health
{"success": true, "spoken_response": "Astral: kernel 2.2.7, local hub installed.",
 "data": {"kernel": true, "hub": true, "version": "2.2.7"}, "error": null}

python3 devkit_functions.py respond "molar mass of water"
{"success": true, "spoken_response": "The molar mass of water (H2O) is 18.015 grams per mole.",
 "data": {"query": "molar mass of water", "from": "hub", "class": "chem"}, "error": null}
```

A device with neither the hub nor the package says so out loud rather than going quiet.
An empty answer means "the agent should take this turn", so a broken install that
returned nothing would look like a working one forever.

## Microphone ownership

This ability runs inside an OpenHome session and returns the turn to the platform agent.
That is distinct from the author's fully local loop, which is a separate program. The
kiosk and that loop must not both own the microphone. OpenHome owns volume and microphone
sensitivity; neither the ability nor the loop forces those settings. See the
[integration notes](https://github.com/Jmesmykil/astral-OpenBrain/blob/main/deploy/PLATFORM-HARDENING.md)
for the checked device sync and dispatch patches and their verification boundaries.
