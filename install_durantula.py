#!/usr/bin/env python3
"""
Durantula Wing Enhancement Mod installer for ToLiss A319 / A320 / A321
======================================================================

Performs the .obj and .acf edits from the Durantula "ToLiss A319 / A320 /
A321 Wing Enhancement MOD" manual for you, so you don't have to do them by
hand in Notepad++ / Plane Maker.

To use it: drop the downloaded Durantula_ToLiss_* folders and this installer
(script or executable) into the same folder as your aircraft's .acf file,
then run it from there.

The mod has two installable parts - install either or both:

  Flaps    - New flaps and flap-track fairings.  Deletes the stock
             flap-fairing TRIS from the wing OBJs, copies the new flaps OBJ +
             textures into objects/, adds the flaps OBJ to every .acf, and -
             for whichever CEO engines are actually fitted - deletes the
             obsolete 'kit' TRIS from the Carda CFM/IAE OBJs or stock
             engines.obj.

  Wingflex - Replaces the stock 'anim/winglex' winglet animations with
             X-Plane native 'wing_tip_deflection_deg' animations and sets the
             wing-damping properties in every .acf.

Which CEO / NEO engines are fitted - Carda or stock, one family or both - is
read straight from the .acf, so the only thing the installer ever asks about
engines is which flap mesh to use on an aircraft that carries *both* families
(e.g. an A320neo with the CEO expansion).  An aircraft can be CEO-only (e.g.
the A319), NEO-only (an A320neo with no CEO expansion), or both; all three
are handled.

Every edit is content-based (search/replace on geometry/animation
signatures), so it survives other mods having shifted line numbers and is
safe to re-run.  Backups (*.bak) are written before any file is modified.

Usage:
    # Interactive - just run it from inside the aircraft folder:
    python install_durantula.py

    # Non-interactive:
    python install_durantula.py --aircraft a320 --parts both \\
        --flaps-engine neo --textures new \\
        --aircraft-dir "/path/to/Airbus A320neo (ToLiss)"
"""

import abc
import argparse
import re
import shutil
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

SEPARATOR_WIDTH = 64


# ─── Constants ────────────────────────────────────────────────────────────────

# _obj_flags bitfield (per Plane Maker):
#   shadow:    0=none, 8=Prefill, 16=All Views, 24=All Views + High Res
#   lighting:  +1 Inside, +2 Glass(outside)
FLAGS_SHADOW_ALL_VIEWS = 24  # All Views + High Res shadow

# Misc-object attach point for the new flaps OBJ, taken straight from the mod's
# manual (Plane Maker shows LONG 099.47, LAT 000.00, VERT 000.40, which maps to
# ACF z / x / y).  This is the SAME for all three aircraft and both flap meshes.
#
# Crucially this is NOT the wing's own attach point (z=20.70): the flaps OBJ
# carries a large baked-in transform (a ~24 m translation plus a 180° flip), so
# it has to be attached far aft to land on the wing.  Attaching it at the wing's
# z=20.70 - the obvious-looking but wrong assumption - drops the flaps ~80 m
# forward, out in front of the aircraft.
FLAPS_X, FLAPS_Y, FLAPS_Z = 0.0, 0.40, 99.47

# Wing-damping properties set by the Wingflex part (manual section 5, step 9).
WING_DAMP_PROPERTIES = {
    "acf/_wing_damp_rat": "1.65",
    "acf/_wing_frac_fuel": "0.600000000",
    "acf/_wing_frac_mass": "0.400000000",
    "acf/_wing_mid_dihed_per_g": "2.1",
}

# All flaps OBJ basenames the mod can install - purged from the ACF on re-run
# so switching CEO/NEO (or re-running) leaves no stale object.
ALL_FLAPS_OBJS = ["flaps_new_321.obj", "flaps_new_CEO.obj", "flaps_new_NEO.obj"]


# ─── Wingflex: the 'anim/winglex' → 'wing_tip_deflection_deg' replacement ─────
#
# Each stock winglet animation is keyed on the custom 'anim/winglex' dataref.
# The mod swaps it for X-Plane's native per-wing-part tip deflection dataref,
# 'sim/flightmodel2/wing/wing_tip_deflection_deg[N]', with the keyframes the
# mod author provides (the six "cases" in the manual's DATA.txt).
#
# Which case a given winglex animation belongs to is identified by the first
# value of the ANIM_trans of its enclosing winglet-root block (the manual's
# "Number"):
#
#     -6.335      → Case 1 → deg[2]      6.335     → Case 2 → deg[3]
#     -6.9650002  → Case 3 → deg[4]      6.9650002 → Case 4 → deg[5]
#     -3.13994    → Case 5 → deg[4]      3.13994   → Case 6 → deg[5]
#
# Negative (left wing) → rotation axis "0 0 1"; positive (right) → "0 0 -1".


@dataclass(frozen=True)
class WinglexCase:
    deg_index: int          # wing_tip_deflection_deg array index
    axis_sign: str          # "1" or "-1" for the Z component of the rotate axis
    static_rotate: str      # the static ANIM_rotate X-tilt value for this root
    keys: tuple             # six (angle, deflection) keyframe pairs, as strings


# Keyed by round(ANIM_trans_first_value, 3) so the slightly different float
# spellings across files (-6.335 / 6.335, -6.9650002, -3.13994 / 3.13993, …)
# all map cleanly.
_KF = {
    "set_a": (("-16", "4.2"), ("-15", "4.2"), ("-6", "1.3"), ("0", "-2.6"), ("15", "-7.2"), ("16", "-7.2")),
    "set_b": (("-16", "1.9"), ("-15", "1.9"), ("-6", "-0.7"), ("0", "-2.2"), ("15", "-4.2"), ("16", "-4.2")),
    "set_c": (("-16", "1"), ("-15", "1"), ("-6", "0"), ("0", "-1.7"), ("15", "-3"), ("16", "-3")),
}

WINGLEX_CASES: dict[float, WinglexCase] = {
    -6.335: WinglexCase(2, "1", "-0.028074932", _KF["set_a"]),    # Case 1
    6.335: WinglexCase(3, "-1", "-0.028074932", _KF["set_a"]),    # Case 2
    -6.965: WinglexCase(4, "1", "2.077545", _KF["set_b"]),        # Case 3
    6.965: WinglexCase(5, "-1", "2.077545", _KF["set_b"]),        # Case 4
    -3.14: WinglexCase(4, "1", "-1.167688", _KF["set_c"]),        # Case 5
    3.14: WinglexCase(5, "-1", "-1.167688", _KF["set_c"]),        # Case 6
}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def format_float32(val: float) -> str:
    """Format a float in X-Plane's single-precision 9-decimal-place style."""
    (unpacked,) = struct.unpack("f", struct.pack("f", val))
    return f"{unpacked:.9f}"


def _backup(filepath: Path) -> None:
    bak = filepath.with_suffix(filepath.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(filepath, bak)


def _read_lines(filepath: Path) -> list[str]:
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        return f.readlines()


def _write_lines(filepath: Path, lines: list[str]) -> None:
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, SEPARATOR_WIDTH - len(title) - 4))


def ask_choice(prompt: str, options: list[tuple[str, str]]) -> str:
    """Ask the user to pick one of (key, label) options.  Returns the key."""
    print(prompt)
    for n, (_key, label) in enumerate(options, start=1):
        print(f"  {n} - {label}")
    valid = {str(n): key for n, (key, _l) in enumerate(options, start=1)}
    while True:
        raw = input(f"\nEnter 1-{len(options)}: ").strip()
        if raw in valid:
            return valid[raw]
        print(f"  Invalid choice. Please enter 1-{len(options)}.")


# ─── OBJ editing: TRIS-batch deletion (content-based) ─────────────────────────


def delete_tris_signature(filepath: Path, a: int, b: int) -> str:
    """Delete the unique line ``TRIS <a> <b>`` from an OBJ file.

    Matches on the TRIS batch's offset/count signature (whitespace-tolerant)
    rather than a line number, so it survives other mods having shifted the
    file.  Returns a short status string.
    """
    lines = _read_lines(filepath)
    want = ["TRIS", str(a), str(b)]
    matches = [i for i, ln in enumerate(lines) if ln.split() == want]
    if not matches:
        return f"OK (already removed: TRIS {a} {b})"
    if len(matches) > 1:
        return f"SKIPPED (TRIS {a} {b} not unique: {len(matches)} matches)"
    _backup(filepath)
    del lines[matches[0]]
    _write_lines(filepath, lines)
    return f"deleted TRIS {a} {b}"


# ─── OBJ editing: winglex → wing_tip_deflection replacement ───────────────────


class WinglexTransformer:
    """Rewrites stock 'anim/winglex' winglet animations into X-Plane native
    'wing_tip_deflection_deg' keyframed animations (the Wingflex part)."""

    _TRANS_RE = re.compile(r"^\s*ANIM_trans\s+(-?\d+(?:\.\d+)?)")
    # Two stock winglex forms (verified across every affected OBJ):
    #   (A) keyframed:  ANIM_rotate_begin <ax> <ay> <az>  anim/winglex
    #                   ANIM_rotate_key 0 0
    #                   ANIM_rotate_key 1 1.000137
    #                   ANIM_rotate_end
    #   (B) one-line:   ANIM_rotate <ax> <ay> <az> <m1> <m2> <v1> <v2>  anim/winglex

    @classmethod
    def _case_for_trans(cls, line: str) -> float | None:
        m = cls._TRANS_RE.match(line)
        if not m:
            return None
        key = round(float(m.group(1)), 3)
        return key if key in WINGLEX_CASES else None

    @staticmethod
    def _emit_deflection(ind: str, case: WinglexCase, *, with_static: bool) -> list[str]:
        out: list[str] = []
        if with_static:
            out.append(f"{ind}ANIM_rotate\t1\t0\t0\t{case.static_rotate}\t{case.static_rotate}\n")
        out.append(
            f"{ind}ANIM_rotate_begin\t0\t0\t{case.axis_sign}\t"
            f"sim/flightmodel2/wing/wing_tip_deflection_deg[{case.deg_index}]\n"
        )
        for angle, defl in case.keys:
            out.append(f"{ind}ANIM_rotate_key\t{angle}\t{defl}\n")
        out.append(f"{ind}ANIM_rotate_end\n")
        return out

    @classmethod
    def transform(cls, filepath: Path) -> tuple[int, list[str]]:
        """Replace every winglex animation in-place.  Returns
        (num_replaced, warnings)."""
        lines = _read_lines(filepath)
        out: list[str] = []
        warnings: list[str] = []
        current_case: float | None = None
        replaced = 0
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            stripped = line.strip()

            # Track the enclosing winglet-root case as we descend the file.
            new_case = cls._case_for_trans(line)
            if new_case is not None:
                current_case = new_case

            if "anim/winglex" in stripped:
                if current_case is None:
                    warnings.append(f"line {i + 1}: winglex with no known case context - left unchanged")
                    out.append(line)
                    i += 1
                    continue
                case = WINGLEX_CASES[current_case]
                ind = _leading_ws(line)

                if stripped.startswith("ANIM_rotate_begin"):
                    # Form A: consume begin + 2 keys + end (4 lines).
                    block = lines[i : i + 4]
                    looks_right = (
                        len(block) == 4
                        and block[1].strip().startswith("ANIM_rotate_key")
                        and block[2].strip().startswith("ANIM_rotate_key")
                        and block[3].strip().startswith("ANIM_rotate_end")
                    )
                    if not looks_right:
                        warnings.append(f"line {i + 1}: unexpected keyframe-form winglex block - left unchanged")
                        out.append(line)
                        i += 1
                        continue
                    out.extend(cls._emit_deflection(ind, case, with_static=False))
                    replaced += 1
                    i += 4
                    continue

                if stripped.startswith("ANIM_rotate"):
                    # Form B: replace the single one-line rotate.
                    out.extend(cls._emit_deflection(ind, case, with_static=True))
                    replaced += 1
                    i += 1
                    continue

                warnings.append(f"line {i + 1}: winglex on unrecognised directive - left unchanged")
                out.append(line)
                i += 1
                continue

            out.append(line)
            i += 1

        if replaced:
            _backup(filepath)
            _write_lines(filepath, out)
        return replaced, warnings


# ─── ACF Editor ───────────────────────────────────────────────────────────────


@dataclass
class ACFObject:
    """A Misc Object entry to add to the ACF."""

    file_stl: str
    flags: int = FLAGS_SHADOW_ALL_VIEWS
    hide_dataref: str = ""
    x: float = FLAPS_X
    y: float = FLAPS_Y
    z: float = FLAPS_Z
    body: int = -1
    gear: int = -1
    wing: int = -1
    phi_ref: float = 0.0
    psi_ref: float = 0.0
    the_ref: float = 0.0
    is_internal: int = 0
    steers_with_gear: int = 0


class ACFEditor:
    """Reads, modifies, and writes X-Plane .acf property files."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self._header_lines: list[str] = []
        self._properties: dict[str, str] = {}
        self._footer_lines: list[str] = []
        self._read()

    def _read(self) -> None:
        in_props = past_props = False
        for line in _read_lines(self.filepath):
            stripped = line.rstrip("\n\r")
            if stripped.startswith("P "):
                in_props, past_props = True, False
                parts = stripped.split(" ", 2)
                self._properties[parts[1]] = parts[2] if len(parts) > 2 else ""
            elif in_props:
                in_props, past_props = False, True
                self._footer_lines.append(line)
            elif past_props:
                self._footer_lines.append(line)
            else:
                self._header_lines.append(line)

    def save(self, backup: bool = True) -> None:
        if backup:
            _backup(self.filepath)
        with open(self.filepath, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(self._header_lines)
            for key in sorted(self._properties):
                f.write(f"P {key} {self._properties[key]}\n")
            f.writelines(self._footer_lines)

    # ── Queries ────────────────────────────────────────────────────────────

    def get_obja_count(self) -> int:
        return int(self._properties.get("_obja/count", "0"))

    def get_obja_entries(self) -> dict[int, dict[str, str]]:
        entries: dict[int, dict[str, str]] = {}
        for key, value in self._properties.items():
            if key.startswith("_obja/") and key != "_obja/count":
                _, idx_str, *prop_parts = key.split("/")
                entries.setdefault(int(idx_str), {})["/".join(prop_parts)] = value
        return entries

    def has_object(self, filename: str) -> bool:
        return any(
            k.endswith("/_v10_att_file_stl") and v == filename
            for k, v in self._properties.items()
        )

    def set_property(self, key: str, value: str) -> bool:
        """Set a P-property; return True if it changed."""
        if self._properties.get(key) == value:
            return False
        self._properties[key] = value
        return True

    # ── Mutation ───────────────────────────────────────────────────────────

    def remove_and_add_objects(
        self,
        filenames_to_remove: list[str],
        objects_to_add: list[ACFObject],
    ) -> list[str]:
        """Remove specified objects (by filename) and append new ones,
        re-indexing the _obja/* key space.  Returns the removed filenames."""
        entries = self.get_obja_entries()
        remove_set = set(filenames_to_remove)

        indices_to_remove: set[int] = set()
        removed_names: list[str] = []
        for idx, props in entries.items():
            stl = props.get("_v10_att_file_stl", "")
            if stl in remove_set:
                indices_to_remove.add(idx)
                removed_names.append(stl)

        filtered_add = [
            obj
            for obj in objects_to_add
            if obj.file_stl in remove_set or not self.has_object(obj.file_stl)
        ]

        if not indices_to_remove and not filtered_add:
            return removed_names

        for k in [k for k in self._properties if k.startswith("_obja/") and k != "_obja/count"]:
            del self._properties[k]

        survivors = [
            props for idx, props in sorted(entries.items()) if idx not in indices_to_remove
        ]
        new_entries = {i: props for i, props in enumerate(survivors)}
        next_idx = len(new_entries)
        for obj in filtered_add:
            new_entries[next_idx] = self._acf_obj_to_props(obj)
            next_idx += 1

        for idx, props in sorted(new_entries.items()):
            for prop_name, value in sorted(props.items()):
                self._properties[f"_obja/{idx}/{prop_name}"] = value
        self._properties["_obja/count"] = str(len(new_entries))

        return removed_names

    @staticmethod
    def _acf_obj_to_props(obj: ACFObject) -> dict[str, str]:
        props: dict[str, str] = {
            "_obj_flags": str(obj.flags),
            "_v10_att_body": str(obj.body),
            "_v10_att_file_stl": obj.file_stl,
            "_v10_att_gear": str(obj.gear),
            "_v10_att_phi_ref": format_float32(obj.phi_ref),
            "_v10_att_psi_ref": format_float32(obj.psi_ref),
            "_v10_att_the_ref": format_float32(obj.the_ref),
            "_v10_att_wing": str(obj.wing),
            "_v10_att_x_acf_prt_ref": format_float32(obj.x),
            "_v10_att_y_acf_prt_ref": format_float32(obj.y),
            "_v10_att_z_acf_prt_ref": format_float32(obj.z),
            "_v10_is_internal": str(obj.is_internal),
            "_v10_steers_with_gear": str(obj.steers_with_gear),
        }
        if obj.hide_dataref:
            props["_obj_hide_dataref"] = obj.hide_dataref
        return props


# ─── Engine 'kit' TRIS deletions (CEO only) ──────────────────────────────────
#
# These obsolete TRIS batches overlap the new flap-track fairings and must be
# removed for CEO engine users (manual sections 3/4, steps 20-22).  Signatures
# are shared across A319 / A320 / A321.

# Carda CFM/IAE engine OBJ → TRIS signature to delete.
CARDA_ENGINE_TRIS: dict[str, tuple[int, int]] = {
    "CFM56/cfm56_l_engine.obj": (154155, 1692),
    "CFM56/cfm56_r_engine.obj": (154155, 1692),
    "V2500/iae_l_engine.obj": (140673, 1692),
    "V2500/iae_r_engine.obj": (137439, 1692),
}

# Stock (non-Carda) engines.obj TRIS batches to delete for default CEO engines.
STOCK_ENGINE_TRIS: list[tuple[int, int]] = [
    (17934, 888),
    (16152, 888),
    (13932, 888),
    (13044, 888),
]


# ─── Engine-family detection ─────────────────────────────────────────────────
#
# Which engines an aircraft carries is read from the .acf's misc objects.  Any
# ToLiss can be CEO-only (e.g. the A319), NEO-only (an A320neo without the CEO
# expansion), or carry both families at once (an A320neo with the CEO
# expansion, or an A321 with both) - so CEO and NEO are tracked independently,
# not as one either/or choice.
#
#   CEO engines:  Carda CFM56/… , V2500/…   or   stock engines.obj
#   NEO engines:  Carda LEAP Engines/… , PW Engines/…
#                 or stock neo.obj / LEAP1A.obj / leapfast.obj
#
# Object names mirror the companion Carda installer, which is what writes them.
CEO_CARDA_PREFIXES = ("CFM56/", "V2500/")
NEO_PREFIXES = ("LEAP Engines/", "PW Engines/")
STOCK_CEO_OBJ = "engines.obj"
STOCK_NEO_OBJS = frozenset({"neo.obj", "LEAP1A.obj", "leapfast.obj"})


@dataclass(frozen=True)
class EngineSetup:
    """Which engine families the aircraft carries, detected from its .acf."""

    has_ceo: bool
    has_neo: bool
    ceo_is_carda: bool  # CEO geometry is Carda CFM/IAE (else stock engines.obj)

    @property
    def label(self) -> str:
        parts: list[str] = []
        if self.has_ceo:
            parts.append("CEO/Carda" if self.ceo_is_carda else "CEO/stock")
        if self.has_neo:
            parts.append("NEO")
        return " + ".join(parts) if parts else "none detected"


# ─── Aircraft configuration ──────────────────────────────────────────────────


@dataclass
class AircraftConfig(abc.ABC):
    """Per-aircraft differences for the Durantula installer."""

    name: str

    # Engine the airframe ships as - used as the default flap mesh when the
    # aircraft carries both CEO and NEO engines.  (Ignored on the A321, which
    # has a single mesh.)  A320Config overrides this to "neo".
    default_flaps_engine = "ceo"

    @property
    @abc.abstractmethod
    def wing_l(self) -> str:
        """Left wing OBJ basename (relative to objects/)."""

    @property
    @abc.abstractmethod
    def wing_r(self) -> str:
        """Right wing OBJ basename (relative to objects/)."""

    @property
    @abc.abstractmethod
    def wing_l_tris(self) -> list[tuple[int, int]]:
        """Flap-fairing TRIS signatures to delete from the left wing OBJ."""

    @property
    @abc.abstractmethod
    def wing_r_tris(self) -> list[tuple[int, int]]:
        """Flap-fairing TRIS signatures to delete from the right wing OBJ."""

    @abc.abstractmethod
    def flaps_obj(self, engine_family: str) -> str:
        """Flaps OBJ basename for the chosen engine family ('ceo'/'neo')."""

    @property
    def has_engine_flaps_variants(self) -> bool:
        """True if the CEO and NEO flap meshes differ (A319/A320); the A321
        ships a single mesh, so the engine choice doesn't affect it."""
        return self.flaps_obj("ceo") != self.flaps_obj("neo")

    @property
    @abc.abstractmethod
    def flaps_source_folder_prefix(self) -> str:
        """Prefix of the downloaded 'New Flaps' source folder for this type."""

    @abc.abstractmethod
    def texture_choices(self) -> list[tuple[str, str]]:
        """Available (key, label) flaps texture sets, or [] if not applicable."""

    @abc.abstractmethod
    def texture_subdir(self, texture_key: str) -> str:
        """Source sub-folder (under the New Flaps folder) for a texture key."""

    @property
    def num(self) -> str:
        """The numeric suffix used in light/particle filenames, e.g. '321'."""
        return self.name[1:]

    @property
    def wingflex_objs(self) -> list[str]:
        """OBJs (relative to objects/) that carry winglex animations.

        ToLiss ships three lights OBJs - a base plus _XP11 / _XP12 variants -
        and the XP11 and XP12 .acf files load the matching one, so all three
        are converted (the transform skips any that are absent).  The manual
        lists only the base + XP12, but the XP11 .acf references the _XP11
        OBJ, so it needs converting too or XP11 winglet lights stay on the old
        animation.
        """
        return [
            self.wing_l,
            self.wing_r,
            "wings_glass.obj",
            "Decals.obj",
            f"lights_out{self.num}.obj",
            f"lights_out{self.num}_XP11.obj",
            f"lights_out{self.num}_XP12.obj",
            f"particles/Particles{self.num}.obj",
        ]


class _A319A320Base(AircraftConfig):
    """Shared config for the A319 and A320 (same wing OBJ names, same flap
    TRIS signatures and flaps OBJs per the manual; only the light/particle
    filename suffix differs)."""

    wing_l = "wingL.obj"
    wing_r = "wingR.obj"
    wing_l_tris = [(27801, 1992), (24666, 2031), (9357, 1128), (7647, 504), (29793, 1716)]
    wing_r_tris = [(36225, 1992), (38217, 1992), (8232, 1128), (34233, 1992), (7728, 504)]
    flaps_source_folder_prefix = "Durantula_ToLiss_New_Flaps_A319_A320"

    def flaps_obj(self, engine_family: str) -> str:
        return "flaps_new_NEO.obj" if engine_family == "neo" else "flaps_new_CEO.obj"

    def texture_choices(self) -> list[tuple[str, str]]:
        return [("new", "New textures (Texture_New)"), ("old", "Old textures (Texture_Old)")]

    def texture_subdir(self, texture_key: str) -> str:
        return "Texture_Old" if texture_key == "old" else "Texture_New"


class A319Config(_A319A320Base):
    def __init__(self) -> None:
        super().__init__(name="A319")


class A320Config(_A319A320Base):
    default_flaps_engine = "neo"  # the A320neo ships as a neo

    def __init__(self) -> None:
        super().__init__(name="A320")


class A321Config(AircraftConfig):
    """ToLiss A321.  Own wing OBJ names (wing321L/R) and a single flaps OBJ
    (flaps_new_321.obj - no CEO/NEO split); a single Texture folder."""

    wing_l = "wing321L.obj"
    wing_r = "wing321R.obj"
    wing_l_tris = [
        (38541, 1716), (36549, 1992), (34518, 2031), (28515, 2742), (2778, 4200),
        (6978, 156), (21768, 156), (21924, 156), (8712, 156), (8868, 156),
        (26841, 1674), (0, 2778), (24195, 504),
    ]
    wing_r_tris = [
        (45015, 1992), (47007, 1992), (48999, 1992), (37887, 2742), (2772, 3276),
        (6048, 864), (35757, 2130), (0, 2196), (2196, 576), (33105, 510),
    ]
    flaps_source_folder_prefix = "Durantula_ToLiss_New_Flaps_A321"

    def __init__(self) -> None:
        super().__init__(name="A321")

    def flaps_obj(self, engine_family: str) -> str:
        return "flaps_new_321.obj"

    def texture_choices(self) -> list[tuple[str, str]]:
        return []  # single Texture folder

    def texture_subdir(self, texture_key: str) -> str:
        return "Texture"


AIRCRAFT_CONFIGS: dict[str, type[AircraftConfig]] = {
    "a319": A319Config,
    "a320": A320Config,
    "a321": A321Config,
}


# ─── Source-file location ────────────────────────────────────────────────────


def find_source_dir(search_roots: list[Path], folder_prefix: str) -> Path | None:
    """Find a downloaded Durantula source folder whose name starts with
    ``folder_prefix`` (e.g. 'Durantula_ToLiss_Wingflex'), searching each root
    shallowly (the root itself, its children, and grandchildren)."""
    seen: set[Path] = set()
    for root in search_roots:
        if not root or not root.is_dir():
            continue
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        if root.name.startswith(folder_prefix):
            return root
        for child in sorted(root.iterdir()):
            if child.is_dir() and child.name.startswith(folder_prefix):
                return child
            if child.is_dir():
                for gchild in sorted(child.iterdir()):
                    if gchild.is_dir() and gchild.name.startswith(folder_prefix):
                        return gchild
    return None


def find_file(root: Path, name: str) -> Path | None:
    """Find the first file named ``name`` anywhere under ``root``."""
    if root is None or not root.is_dir():
        return None
    direct = root / name
    if direct.is_file():
        return direct
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


# ─── Install steps ───────────────────────────────────────────────────────────


def install_flaps(
    config: AircraftConfig,
    obj_dir: Path,
    acf_files: list[Path],
    flaps_engine: str,
    setup: EngineSetup,
    flaps_obj_source: Path,
    texture_files: list[Path],
) -> None:
    flaps_obj_name = config.flaps_obj(flaps_engine)

    # 1. Delete the stock flap-track-fairing TRIS from the wing OBJs.
    section("Flaps: wing OBJ TRIS deletions")
    for wing_obj, tris in ((config.wing_l, config.wing_l_tris), (config.wing_r, config.wing_r_tris)):
        path = obj_dir / wing_obj
        if not path.exists():
            print(f"  {wing_obj}: not found (skipped)")
            continue
        results = [delete_tris_signature(path, a, b) for a, b in tris]
        n_deleted = sum(1 for r in results if r.startswith("deleted"))
        n_skipped = [r for r in results if r.startswith("SKIPPED")]
        print(f"  {wing_obj}: deleted {n_deleted}/{len(tris)} TRIS batch(es)")
        for r in n_skipped:
            print(f"    WARNING: {r}")

    # 2. Copy the new flaps OBJ + textures into objects/.
    section("Flaps: copy OBJ + textures into objects/")
    obj_dir.mkdir(parents=True, exist_ok=True)
    dest = obj_dir / flaps_obj_name
    shutil.copy2(flaps_obj_source, dest)
    print(f"  copied {flaps_obj_name}  (from {flaps_obj_source.parent.name}/)")
    for tex in texture_files:
        shutil.copy2(tex, obj_dir / tex.name)
        print(f"  copied {tex.name}")
    if not texture_files:
        print("  (no flaps textures found to copy - skipped)")

    # 3. Add the flaps OBJ to every ACF (purging any prior flaps object first).
    section("Flaps: ACF misc-object addition")
    flaps_object = ACFObject(flaps_obj_name)
    for acf_path in acf_files:
        editor = ACFEditor(acf_path)
        removed = editor.remove_and_add_objects(
            filenames_to_remove=ALL_FLAPS_OBJS,
            objects_to_add=[flaps_object],
        )
        editor.save(backup=True)
        action = "refreshed" if flaps_obj_name in removed else "added"
        print(f"  {acf_path.name}: {action} {flaps_obj_name}  (object count {editor.get_obja_count()})")

    # 4. CEO engine 'kit' TRIS deletions, for whichever CEO engines are fitted.
    #    NEO engines have no overlapping kit geometry, and this is independent
    #    of the flap-mesh choice above: an aircraft carrying *both* families
    #    still needs its CEO kit removed.
    if not setup.has_ceo:
        print("\n  (No CEO engines fitted - no engine OBJ TRIS deletions needed)")
    elif setup.ceo_is_carda:
        section("Flaps: Carda CEO engine OBJ TRIS deletions")
        any_found = False
        for rel, (a, b) in CARDA_ENGINE_TRIS.items():
            path = obj_dir / rel
            if not path.exists():
                continue
            any_found = True
            print(f"  {rel}: {delete_tris_signature(path, a, b)}")
        if not any_found:
            print("  no Carda engine OBJs found (skipped)")
    else:
        section("Flaps: stock engines.obj TRIS deletions (default CEO)")
        path = obj_dir / "engines.obj"
        if not path.exists():
            print("  engines.obj: not found (skipped)")
        else:
            results = [delete_tris_signature(path, a, b) for a, b in STOCK_ENGINE_TRIS]
            n_deleted = sum(1 for r in results if r.startswith("deleted"))
            print(f"  engines.obj: deleted {n_deleted}/{len(STOCK_ENGINE_TRIS)} TRIS batch(es)")
            for r in results:
                if r.startswith("SKIPPED"):
                    print(f"    WARNING: {r}")


def install_wingflex(
    config: AircraftConfig,
    obj_dir: Path,
    acf_files: list[Path],
) -> None:
    # 1. Replace winglex animations in every affected OBJ.
    section("Wingflex: winglex → wing_tip_deflection in OBJs")
    for rel in config.wingflex_objs:
        path = obj_dir / rel
        if not path.exists():
            print(f"  {rel}: not found (skipped)")
            continue
        replaced, warnings = WinglexTransformer.transform(path)
        if replaced:
            print(f"  {rel}: replaced {replaced} winglex animation(s)")
        else:
            print(f"  {rel}: OK (no winglex found - already done?)")
        for w in warnings:
            print(f"    WARNING: {w}")

    # 2. Set the wing-damping properties in every ACF.
    section("Wingflex: ACF wing-damping properties")
    for acf_path in acf_files:
        editor = ACFEditor(acf_path)
        changed = [k for k, v in WING_DAMP_PROPERTIES.items() if editor.set_property(k, v)]
        if changed:
            editor.save(backup=True)
            print(f"  {acf_path.name}: set {len(changed)} wing property(ies)")
        else:
            print(f"  {acf_path.name}: OK (wing properties already set)")


# ─── Main ─────────────────────────────────────────────────────────────────────


def detect_engine_setup(acf_files: list[Path]) -> EngineSetup:
    """Detect which engine families the aircraft carries by inspecting the
    misc objects in its .acf file(s)."""
    ceo_carda = ceo_stock = neo = False
    for acf_path in acf_files:
        editor = ACFEditor(acf_path)
        for props in editor.get_obja_entries().values():
            stl = props.get("_v10_att_file_stl", "")
            if stl.startswith(CEO_CARDA_PREFIXES):
                ceo_carda = True
            elif stl.startswith(NEO_PREFIXES):
                neo = True
            elif stl == STOCK_CEO_OBJ:
                ceo_stock = True
            elif stl in STOCK_NEO_OBJS:
                neo = True
    return EngineSetup(
        has_ceo=ceo_carda or ceo_stock,
        has_neo=neo,
        ceo_is_carda=ceo_carda,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Durantula Wing Enhancement Mod installer for ToLiss A319 / A320 / A321"
    )
    parser.add_argument("--aircraft-dir", type=Path, default=Path.cwd(),
                        help="Path to the ToLiss aircraft folder (default: current directory)")
    parser.add_argument("--mod-dir", type=Path, default=None,
                        help="Folder containing the downloaded Durantula_ToLiss_* folders "
                             "(default: next to this script and inside the aircraft folder)")
    parser.add_argument("--aircraft", choices=list(AIRCRAFT_CONFIGS), default=None,
                        help="Aircraft type (skips prompt)")
    parser.add_argument("--parts", choices=["flaps", "wingflex", "both"], default=None,
                        help="Which part(s) to install (skips prompt)")
    parser.add_argument("--flaps-engine", choices=["ceo", "neo"], default=None,
                        help="Which flap mesh to install on an A319/A320 that carries "
                             "both CEO and NEO engines. Auto-detected when only one "
                             "family is fitted; ignored on the A321 (single mesh).")
    parser.add_argument("--textures", choices=["new", "old"], default=None,
                        help="Flaps texture set for A319/A320 (skips prompt)")
    args = parser.parse_args()
    aircraft_dir: Path = args.aircraft_dir.resolve()

    print("=" * SEPARATOR_WIDTH)
    print(" Durantula Wing Enhancement Mod - Installer v1.0r1")
    print("=" * SEPARATOR_WIDTH)

    # ── Aircraft selection ──
    if args.aircraft is not None:
        aircraft_key = args.aircraft
    else:
        aircraft_key = ask_choice(
            "\nWhich aircraft are you installing for?",
            [("a319", "ToLiss A319"), ("a320", "ToLiss A320"), ("a321", "ToLiss A321")],
        )
    config = AIRCRAFT_CONFIGS[aircraft_key]()

    # ── Validation: aircraft folder ──
    acf_files = sorted(aircraft_dir.glob("*.acf"))
    obj_dir = aircraft_dir / "objects"
    if not acf_files:
        print(f"\nERROR: No .acf files found in {aircraft_dir}")
        print(f"Run this from the ToLiss {config.name} aircraft folder, or use --aircraft-dir.")
        sys.exit(1)
    if not obj_dir.is_dir():
        print(f"\nERROR: objects/ folder not found in {aircraft_dir}")
        sys.exit(1)

    # ── Parts selection ──
    if args.parts is not None:
        parts = args.parts
    else:
        parts = ask_choice(
            "\nWhich part(s) of the mod do you want to install?",
            [("both", "Flaps + Wingflex (recommended)"),
             ("flaps", "New Flaps and Flap Track Fairings only"),
             ("wingflex", "Wingflex only")],
        )
    do_flaps = parts in ("flaps", "both")
    do_wingflex = parts in ("wingflex", "both")

    # ── Engine detection → flap-mesh choice (flaps part only) ──
    # CEO/NEO - Carda or stock, one family or both - is read from the .acf, so
    # we only ever have to *ask* which flap mesh to use, and only on an
    # A319/A320 that carries both families.
    setup = EngineSetup(has_ceo=False, has_neo=False, ceo_is_carda=False)
    flaps_engine = config.default_flaps_engine
    if do_flaps:
        setup = detect_engine_setup(acf_files)
        if not config.has_engine_flaps_variants:
            flaps_engine = "ceo"  # A321: single mesh, value is ignored
        elif args.flaps_engine is not None:
            flaps_engine = args.flaps_engine
        elif setup.has_ceo and not setup.has_neo:
            flaps_engine = "ceo"
        elif setup.has_neo and not setup.has_ceo:
            flaps_engine = "neo"
        else:
            # Both families (or neither) detected - the flap mesh is a real
            # choice; ask, defaulting to the engine the airframe ships as.
            opts = [("ceo", "CEO flaps (for CFM56 / V2500 engines)"),
                    ("neo", "NEO flaps (for LEAP / PW engines)")]
            if config.default_flaps_engine == "neo":
                opts.reverse()
            flaps_engine = ask_choice(
                "\nThis aircraft carries both CEO and NEO engines."
                "\nWhich flap mesh do you want? (Pick the engines you fly most.)",
                opts,
            )

    # ── Texture selection (A319/A320 flaps only) ──
    texture_key = "new"
    if do_flaps and config.texture_choices():
        if args.textures is not None:
            texture_key = args.textures
        else:
            texture_key = ask_choice(
                "\nWhich flap texture set do you want?", config.texture_choices()
            )

    # ── Locate source folders ──
    script_dir = Path(__file__).resolve().parent
    search_roots = [
        r for r in (args.mod_dir, script_dir, script_dir / "assets", aircraft_dir) if r
    ]

    flaps_obj_source: Path | None = None
    texture_files: list[Path] = []
    if do_flaps:
        # When installing both parts, the flaps OBJ must come from the Wingflex
        # folder (it has the wingflex baked into the flap mesh); otherwise from
        # the New Flaps folder.
        flaps_obj_name = config.flaps_obj(flaps_engine)
        wingflex_src = find_source_dir(search_roots, "Durantula_ToLiss_Wingflex")
        newflaps_src = find_source_dir(search_roots, config.flaps_source_folder_prefix)

        if do_wingflex and wingflex_src is not None:
            flaps_obj_source = find_file(wingflex_src, flaps_obj_name)
        if flaps_obj_source is None and newflaps_src is not None:
            flaps_obj_source = find_file(newflaps_src, flaps_obj_name)

        if flaps_obj_source is None:
            print(f"\nERROR: could not find the flaps object '{flaps_obj_name}'.")
            print("Drop the downloaded Durantula_ToLiss_* folders into this aircraft")
            print("folder (next to the .acf), or pass --mod-dir pointing at them.")
            sys.exit(1)

        # Textures always come from the New Flaps folder (the Wingflex folder
        # ships OBJs only).  Take the base flaps.png/flaps_NML.png from the
        # chosen texture sub-folder, not from a livery sub-folder.
        if newflaps_src is not None:
            sub = config.texture_subdir(texture_key)
            tex_root = newflaps_src / sub if (newflaps_src / sub).is_dir() else newflaps_src
            for tex_name in ("flaps.png", "flaps_NML.png"):
                direct = tex_root / tex_name
                found = direct if direct.is_file() else find_file(tex_root, tex_name)
                if found is not None:
                    texture_files.append(found)

    if do_wingflex and not do_flaps:
        # Wingflex-only still edits the in-place OBJs/ACFs - no source needed.
        pass

    # ── Pre-run summary ──
    summary = f"\n{config.name}  -  installing: {parts}"
    if do_flaps:
        summary += f"  -  engines: {setup.label}"
        if config.has_engine_flaps_variants:
            summary += f"  -  {flaps_engine.upper()} flap mesh"
    print(summary)
    print(f"Folder:  {aircraft_dir}")
    print(f"ACF(s):  {', '.join(f.name for f in acf_files)}")

    # ── Run ──  (flaps before wingflex, per the manual)
    if do_flaps:
        install_flaps(
            config, obj_dir, acf_files,
            flaps_engine, setup, flaps_obj_source, texture_files,
        )
    if do_wingflex:
        install_wingflex(config, obj_dir, acf_files)

    print("\n" + "=" * SEPARATOR_WIDTH)
    print(" Done!  Backups were written as *.bak next to each changed file.")
    print("=" * SEPARATOR_WIDTH)


if __name__ == "__main__":
    main()
