# Durantula Wing Mod Installer for ToLiss A319 / A320 / A321 v1.0r1

Installer script for the **Durantula "ToLiss A319 / A320 / A321 Wing Enhancement MOD"** by [Durantula2405](https://forums.x-plane.org/profile/843947-durantula2405/) — the new flaps / flap-track-fairings and the wingflex add-on. It performs every `.obj` and `.acf` edit from the mod's installation manual for you, so you don't have to do them by hand in Notepad++ and Plane Maker.

Every edit is **content-based** (search/replace on geometry and animation signatures) rather than line-number based, so it stays correct even when other mods — the [Carda engine mod](https://github.com/iy4vet/xplane-toliss-carda-installer), lights mods, etc. — have already shifted the line numbering. Backups (`*.bak`) are written before any file is changed.

## What the installer does

The mod has two parts; install either or both.

### Flaps (New Flaps and Flap Track Fairings)

1. **Deletes the stock flap-track-fairing `TRIS` batches** from the wing OBJs (`wing[321]L/R.obj`), matched by their geometry signature.
2. **Copies** the new flaps OBJ (`flaps_new_321.obj`, or `flaps_new_CEO.obj` / `flaps_new_NEO.obj` for the A319/A320) plus the `flaps.png` / `flaps_NML.png` textures into `objects/`.
3. **Adds the flaps OBJ to every `.acf`** as a misc object at the wing's attach point.
4. **(CEO engines only)** Deletes the obsolete 'kit' `TRIS` batch that overlaps the new fairings — from the Carda CFM/IAE engine OBJs, or the stock `engines.obj`, depending on which CEO engines are fitted.

> **Engines are auto-detected.** Whether the aircraft carries CEO engines, NEO engines, or **both** (e.g. an A320neo with the CEO expansion, or an A321 with both families) — and whether they're Carda or stock — is read straight from the `.acf`. The CEO 'kit' cleanup runs whenever CEO engines are present, *independently* of the flap mesh. The only engine question you might be asked is which flap mesh (CEO or NEO) to use on an A319/A320 that carries both families; everywhere else it's automatic.

### Wingflex

1. **Replaces the stock `anim/winglex` winglet animations** in the wing / glass / decal / lights / particle OBJs with X-Plane-native `sim/flightmodel2/wing/wing_tip_deflection_deg[N]` keyframed animations (the six "cases" from the mod's `DATA.txt`). Both the keyframed and one-line animation forms are handled, and the correct case is resolved from each winglet-root's position.
2. **Sets the wing-damping properties** (`_wing_damp_rat`, `_wing_frac_fuel`, `_wing_frac_mass`, `_wing_mid_dihed_per_g`) in every `.acf`.

> **Order doesn't matter for you** — the installer always does flaps before wingflex internally (as the manual requires), and because it's content-based you can also re-run it or install the parts separately at any time. When you install both parts, the flaps OBJ is taken from the `Durantula_ToLiss_Wingflex` folder (it has the wingflex baked into the flap mesh), exactly as the manual specifies.

The "New Wing Textures" paint-kit (manual part I) is purely optional artwork and is not automated — open the PNGs in Photoshop/Gimp and drop your finished livery into the aircraft's `liveries/` folder yourself.

## Step 1 — Download the Durantula mod

Get the mod for your aircraft from the X-Plane.org forums and unzip it. You'll get folders with a structure like:

```txt
Durantula_ToLiss_New_Flaps_A321_V1.2/
├── flaps_new_321.obj
└── Texture/
    ├── flaps.png
    └── flaps_NML.png

Durantula_ToLiss_Wingflex_V1.3/
├── flaps_new_321.obj   ← wingflex-baked flaps OBJ, used instead of the one above
├── flaps_new_CEO.obj      when you install both parts
├── flaps_new_NEO.obj
└── …

MANUAL_READ_FIRST_V1.1/
└── MANUAL_READ_FIRST.pdf
```

## Step 2 — Drop everything into the aircraft folder

Put the unzipped `Durantula_ToLiss_*` folders **and the installer** (the script or the binary) into the same folder as your aircraft's `.acf` file:

```txt
Airbus A321 (ToLiss)/          ← your aircraft folder (has the .acf)
├── a321.acf
├── objects/
├── Durantula_ToLiss_New_Flaps_A321_V1.2/
├── Durantula_ToLiss_Wingflex_V1.3/
└── install-durantula-…            ← the installer
```

That's it — **you don't copy any OBJs or textures by hand.** The installer pulls them out of the `Durantula_ToLiss_*` folders, copies them into `objects/`, and wires them into the `.acf` for you. (If you'd rather keep the mod folders elsewhere, point at them with `--mod-dir`.)

## Step 3 — Run the installer

### Option A: Pre-built binary (no Python needed)

Download the binary for your OS from the [Releases](../../releases/latest/) page, drop it in the aircraft folder (Step 2), and run it:

| Platform | Binary |
| -------- | ------ |
| Windows x64 | `install-durantula-windows-x64.exe` |
| Windows ARM64 | `install-durantula-windows-arm64.exe` |
| macOS Apple Silicon | `install-durantula-macos-arm64` |
| macOS Intel | `install-durantula-macos-x64` |
| Linux x64 | `install-durantula-linux-x64` |
| Linux ARM64 | `install-durantula-linux-arm64` |

On Windows just double-click. On macOS/Linux make it executable first (`chmod +x ...`). It asks which aircraft and which part(s) to install — plus, for the A319/A320, which texture set (and, only if the aircraft carries both CEO and NEO engines, which flap mesh).

### Option B: Run with Python

Requires Python 3.10+. No external dependencies. Run it from the aircraft folder:

```bash
cd "/path/to/Airbus A321 (ToLiss)"
python install_durantula.py
```

Fully non-interactive:

```bash
python install_durantula.py \
    --aircraft a320 \
    --parts both \
    --flaps-engine neo \
    --textures new \
    --aircraft-dir "/path/to/Airbus A320neo (ToLiss)"
```

| Flag | Choices | Notes |
| ---- | ------- | ----- |
| `--aircraft` | `a319` / `a320` / `a321` | |
| `--parts` | `flaps` / `wingflex` / `both` | |
| `--flaps-engine` | `ceo` / `neo` | Which flap mesh to install on an **A319/A320 that carries both** CEO and NEO engines. Auto-detected when only one family is fitted; ignored on the A321 (single mesh). The CEO 'kit' TRIS cleanup is always driven by the engines detected in the `.acf`, not by this flag. |
| `--textures` | `new` / `old` | A319/A320 only (the A321 ships a single texture set). |
| `--mod-dir` | path | Where the `Durantula_ToLiss_*` folders live (default: the aircraft folder / next to the installer). |
| `--aircraft-dir` | path | The ToLiss aircraft folder (default: current directory). |

## Re-installing after a ToLiss update

A ToLiss update via SkunkCraftsUpdater restores the stock files, so re-run this installer after every update. It's safe to run repeatedly — it detects work that's already been done and won't duplicate objects or over-delete geometry.

## A note on coverage

The installer supports all three aircraft. The A321 path is verified against the stock ToLiss A321 files (geometry signatures, ACF objects, and every winglex case checked against the mod's `DATA.txt`). The A319/A320 flap-fairing TRIS signatures are taken directly from the manual; the wingflex transformation is geometry-agnostic and works identically on all three. As always, the `*.bak` backups let you roll back instantly if anything looks off.

## Credits and Licensing

Licensed under the GNU GPL v3.

- [Durantula2405](https://forums.x-plane.org/profile/843947-durantula2405/) — author of the Durantula Wing Enhancement Mod.
- Architecture and conventions follow the companion [Carda](https://github.com/iy4vet/xplane-toliss-carda-installer) and [RealWings](https://github.com/iy4vet/xplane-toliss-realwings-installer) ToLiss installers.

Contributions (features or bugfixes) are very welcome.
