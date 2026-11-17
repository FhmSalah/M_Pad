"""Shared validated configuration with conservative, atomic mapping saves."""

import copy
import json
import os
import re
from pathlib import Path
import tempfile
from threading import Lock

from app_paths import config_path
from foreground_app import ForegroundApplication, MACOS_APPLICATION_ALIASES
from monitor_events import VALID_EVENTS
from shortcut_keys import resolve_action

CONFIG_PATH = config_path()
VALID_EVENT_NAMES = {event.decode("ascii") for event in VALID_EVENTS}
LABEL_EVENT_NAMES = VALID_EVENT_NAMES | {"ENC1:ROTATE", "ENC2:ROTATE"}
PROFILE_FORMAT = "MacroPadProfileV1"
APPLICATION_PROFILES = {
    "photoshop.exe": "Photoshop", "afterfx.exe": "After Effects",
    "adobe premiere pro.exe": "Premiere Pro", "blender.exe": "Blender",
    "krita.exe": "Krita", "code.exe": "VS Code",
    "illustrator.exe": "Illustrator", "whatsapp.exe": "WhatsApp", "capcut.exe": "CapCut",
    **{executable: "Browser" for executable in (
        "brave.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "opera_gx.exe")},
}


def application_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*", value):
        raise ValueError("Application has a missing or invalid bundle identifier")
    return value.lower()


def executable_identifier(value):
    """A Windows executable file name such as "krita.exe", never a path."""
    if (not isinstance(value, str) or value != value.strip()
            or not re.fullmatch(r'[^\\/:*?"<>|\x00-\x1f]+\.exe', value, re.IGNORECASE)):
        raise ValueError("Select a Windows application (.exe)")
    return value.lower()


def assignment_identifier(value):
    """Accept a macOS bundle identifier or a Windows executable name."""
    if isinstance(value, str) and value.lower().endswith(".exe"):
        return executable_identifier(value)
    return application_identifier(value)


def label_event(event):
    """Rotation directions share a display name, never an executable mapping."""
    if event in ("ENC1:CW", "ENC1:CCW", "ENC2:CW", "ENC2:CCW"):
        return event.split(":")[0] + ":ROTATE"
    return event


def compile_actions(mappings):
    actions = {}
    for event, action in mappings.items():
        keys = resolve_action(action) if event in VALID_EVENT_NAMES else None
        if keys is None:
            print(f"Ignoring invalid or unsupported config entry: {event}", flush=True)
        elif keys:
            actions[event.encode("ascii")] = keys
    return actions


def compile_profiles(config):
    profiles = {}
    for name, mappings in config.get("profiles", {}).items():
        if name and isinstance(mappings, dict):
            profiles[name] = compile_actions(mappings)
        else:
            print(f"Ignoring invalid profile: {name}", flush=True)
    default = config.get("default_profile")
    if not isinstance(default, str) or default not in profiles:
        print("Invalid default_profile; using General", flush=True)
        default = "General"
        profiles.setdefault(default, {})
    applications = {}
    mappings = config.get("applications", {})
    if not isinstance(mappings, dict):
        print("Ignoring invalid applications mapping", flush=True)
        mappings = {}
    for executable, profile in mappings.items():
        if executable and isinstance(profile, str) and profile in profiles:
            applications[executable.lower()] = profile
        else:
            print(f"Ignoring invalid application mapping: {executable}", flush=True)
    return default, profiles, applications


class ConfigStore:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.lock = Lock()
        self.write_lock = Lock()
        self.error = ""
        self.disk_bytes = None
        try:
            self.disk_bytes = self.path.read_bytes()
            config = json.loads(self.disk_bytes.decode("utf-8-sig"))
            if not isinstance(config, dict) or not isinstance(config.get("profiles"), dict):
                raise ValueError("expected a profiles object")
        except (OSError, UnicodeError, ValueError) as error:
            self.error = f"Cannot load config.json: {error}"
            print(self.error, flush=True)
            config = {"default_profile": "General", "profiles": {"General": {}}}
        self.data = config
        self.compiled = compile_profiles(config)
        self.foreground_application = None
        self.foreground_alias = None
        self.manual_profile = None
        self.active_profile = self._locked_profile() or self.compiled[0]

    def _locked_profile(self):
        profile = self.data.get("locked_profile")
        return profile if isinstance(profile, str) and profile in self.compiled[1] else None

    def locked_profile(self):
        with self.lock:
            return self._locked_profile()

    def current_profile(self):
        with self.lock:
            return self.active_profile

    def _automatic_profile(self):
        candidates = (self.foreground_application, self.foreground_alias)
        # Exact user binding wins, then its legacy alias, then built-in names.
        for identifier in candidates:
            if identifier in self.compiled[2]:
                return self.compiled[2][identifier]
        for identifier in candidates:
            named = APPLICATION_PROFILES.get(identifier)
            if named in self.compiled[1]:
                return named
        return self.compiled[0]

    def update_foreground_profile(self, executable):
        """A manual choice lasts until the foreground application next changes."""
        with self.lock:
            alias = None
            if isinstance(executable, ForegroundApplication):
                alias = executable.alias
                executable = executable.identifier
            executable = executable.lower() if isinstance(executable, str) else None
            alias = MACOS_APPLICATION_ALIASES.get(executable) or alias
            if executable != self.foreground_application:
                self.manual_profile = None
            self.foreground_application = executable
            self.foreground_alias = alias
            self.active_profile = self._locked_profile() or self.manual_profile or self._automatic_profile()
            return self.active_profile

    def active_action_keys(self, event):
        # Read the profile and its actions together; never use a stale watcher copy.
        with self.lock:
            return self.compiled[1].get(self.active_profile, {}).get(event)

    def active_input(self, event):
        """Capture execution and cosmetic metadata from the same profile."""
        with self.lock:
            profile = self.active_profile
            keys = self.compiled[1].get(profile, {}).get(event)
            labels = self.data.get("labels", {})
            labels = labels.get(profile, {}) if isinstance(labels, dict) else {}
            label = labels.get(label_event(event.decode("ascii")), "") if isinstance(labels, dict) else ""
            return keys, profile, label if isinstance(label, str) else ""

    def snapshot(self):
        # Published dictionaries are never mutated, so readers can retain them.
        with self.lock:
            return self.compiled

    def action_keys(self, profile, event):
        with self.lock:
            return self.compiled[1].get(profile, {}).get(event)

    def mapping(self, profile, event):
        with self.lock:
            mappings = self.data["profiles"].get(profile, {})
            return copy.deepcopy(mappings.get(event)) if isinstance(mappings, dict) else None

    def save_mapping(self, profile, event, action):
        if event not in VALID_EVENT_NAMES or resolve_action(action) is None:
            raise ValueError("Invalid assignment")
        def change(candidate):
            self._editable_profile(candidate, profile)[event] = copy.deepcopy(action)
        return self._mutate(change)

    @staticmethod
    def _editable_profile(candidate, profile):
        mappings = candidate["profiles"].get(profile)
        if not isinstance(mappings, dict):
            raise ValueError("Selected profile is not editable")
        return mappings

    def label(self, profile, event):
        with self.lock:
            labels = self.data.get("labels", {})
            labels = labels.get(profile, {}) if isinstance(labels, dict) else {}
            value = labels.get(event, "") if isinstance(labels, dict) else ""
            return value if isinstance(value, str) else ""

    @staticmethod
    def _set_label(candidate, profile, event, label):
        if event not in LABEL_EVENT_NAMES or not isinstance(label, str):
            raise ValueError("Invalid label")
        ConfigStore._editable_profile(candidate, profile)
        labels = candidate.get("labels", {})
        if not isinstance(labels, dict) or not isinstance(labels.get(profile, {}), dict):
            raise ValueError("Invalid labels metadata; refusing to overwrite it")
        if label:
            candidate.setdefault("labels", {}).setdefault(profile, {})[event] = label
        elif profile in labels:
            labels[profile].pop(event, None)
            if not labels[profile]:
                labels.pop(profile)

    def save_label(self, profile, event, label):
        return self._mutate(lambda candidate: self._set_label(candidate, profile, event, label))

    def save_assignment(self, profile, event, action, label):
        """Commit action and visual metadata in a single atomic write."""
        if event not in VALID_EVENT_NAMES or resolve_action(action) is None:
            raise ValueError("Invalid assignment")
        def change(candidate):
            self._editable_profile(candidate, profile)[event] = copy.deepcopy(action)
            self._set_label(candidate, profile, label_event(event), label)
        return self._mutate(change)

    @staticmethod
    def _profile_name(name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Enter a nonempty profile name")
        return name.strip()

    def add_profile(self, name):
        name = self._profile_name(name)
        def change(candidate):
            if name in candidate["profiles"]:
                raise ValueError("A profile with that name already exists")
            candidate["profiles"][name] = {}
        self._mutate(change)
        return name

    def select_profile(self, profile, *, update_default=True):
        """Select manually; optionally retain the legacy change of fallback."""
        def change(candidate):
            self._editable_profile(candidate, profile)
            if update_default:
                candidate["default_profile"] = profile
            if self._locked_profile():
                candidate["locked_profile"] = profile
        def publish():
            self.manual_profile = profile
            self.active_profile = profile
        return self._mutate(change, publish)

    @staticmethod
    def _applications(config):
        applications = config.get("applications", {})
        if not isinstance(applications, dict) or any(
                not isinstance(key, str) or not key.strip() or not isinstance(target, str)
                for key, target in applications.items()):
            raise ValueError("Invalid applications metadata; refusing to overwrite it")
        return applications

    @classmethod
    def _application_bindings(cls, config, identifier, alias):
        return {key: target for key, target in cls._applications(config).items()
                if key.lower() in (identifier, alias)}

    def application_bindings(self, identifier, alias=None):
        identifier = assignment_identifier(identifier)
        with self.lock:
            return self._application_bindings(self.data, identifier, alias)

    def application_assignments(self, profile):
        with self.lock:
            self._editable_profile(self.data, profile)
            return sorted({key.lower() for key, target in self._applications(self.data).items()
                           if target == profile})

    def assign_application(self, profile, identifier, expected_bindings, alias=None):
        identifier = assignment_identifier(identifier)
        def change(candidate):
            self._editable_profile(candidate, profile)
            if self._application_bindings(candidate, identifier, alias) != expected_bindings:
                raise ValueError("Application assignment changed; try again")
            applications = self._applications(candidate)
            candidate["applications"] = {key: target for key, target in applications.items()
                                         if key.lower() != identifier}
            candidate["applications"][identifier] = profile
        return self._mutate(change)

    def remove_application(self, profile, identifier):
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Invalid application assignment")
        identifier = identifier.lower()
        def change(candidate):
            self._editable_profile(candidate, profile)
            applications = self._applications(candidate)
            matches = {key: target for key, target in applications.items() if key.lower() == identifier}
            if any(target != profile for target in matches.values()):
                raise ValueError("Application assignment changed; try again")
            candidate["applications"] = {key: target for key, target in applications.items()
                                         if key.lower() != identifier}
        return self._mutate(change)

    def set_locked_profile(self, profile):
        def change(candidate):
            if profile is not None:
                self._editable_profile(candidate, profile)
            candidate["locked_profile"] = profile
        def publish():
            self.manual_profile = None
            self.active_profile = profile or self._automatic_profile()
        return self._mutate(change, publish)

    def delete_profile(self, profile):
        def change(candidate):
            self._editable_profile(candidate, profile)
            remaining = [name for name, mappings in candidate["profiles"].items()
                         if name and name != profile and isinstance(mappings, dict)]
            if not remaining:
                raise ValueError("At least one profile must remain")
            del candidate["profiles"][profile]
            fallback = candidate.get("default_profile")
            if fallback not in remaining:
                fallback = remaining[0]
                candidate["default_profile"] = fallback
            if candidate.get("locked_profile") == profile:
                candidate["locked_profile"] = fallback
            applications = candidate.get("applications", {})
            if isinstance(applications, dict):
                candidate["applications"] = {exe: name for exe, name in applications.items() if name != profile}
            labels = candidate.get("labels", {})
            if isinstance(labels, dict):
                labels.pop(profile, None)
        def publish():
            if self.manual_profile == profile:
                self.manual_profile = None
            self.active_profile = self._locked_profile() or self.manual_profile or self._automatic_profile()
        return self._mutate(change, publish)

    def rename_profile(self, profile, name):
        name = self._profile_name(name)
        def change(candidate):
            self._editable_profile(candidate, profile)
            if name == profile:
                return
            if name in candidate["profiles"]:
                raise ValueError("A profile with that name already exists")
            candidate["profiles"] = {name if key == profile else key: value
                                     for key, value in candidate["profiles"].items()}
            labels = candidate.get("labels", {})
            if not isinstance(labels, dict):
                raise ValueError("Invalid labels metadata; refusing to overwrite it")
            if profile in labels:
                if name in labels:
                    raise ValueError("Labels already exist for the new profile name")
                labels[name] = labels.pop(profile)
            for field in ("default_profile", "locked_profile"):
                if candidate.get(field) == profile:
                    candidate[field] = name
            applications = candidate.get("applications", {})
            if not isinstance(applications, dict):
                raise ValueError("Invalid applications metadata; refusing to overwrite it")
            candidate["applications"] = {exe: name if target == profile else target
                                          for exe, target in applications.items()}
            # Preserve automatic aliases after the user changes a standard name.
            for exe, target in APPLICATION_PROFILES.items():
                if target == profile and exe not in self.compiled[2]:
                    candidate["applications"][exe] = name
        def publish():
            if self.active_profile == profile:
                self.active_profile = name
            if self.manual_profile == profile:
                self.manual_profile = name
        self._mutate(change, publish)
        return name

    @classmethod
    def read_profile_import(cls, path):
        name, mappings, labels, _ = cls._read_profile_import(path)
        return name, mappings, labels

    @classmethod
    def _read_profile_import(cls, path):
        """Accept one-profile configs, name/mappings envelopes, or bare mappings."""
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (UnicodeError, ValueError) as error:
            raise ValueError(f"Invalid profile JSON: {error}") from error
        if not isinstance(document, dict):
            raise ValueError("Expected a JSON object containing one profile")
        if "format" in document and document["format"] != PROFILE_FORMAT:
            raise ValueError("Unsupported profile file format")
        if "profiles" in document:
            profiles = document["profiles"]
            if not isinstance(profiles, dict) or len(profiles) != 1:
                raise ValueError("Import files must contain exactly one profile")
            name, mappings = next(iter(profiles.items()))
            labels = document.get("labels", {})
            if not isinstance(labels, dict):
                raise ValueError("Invalid imported labels")
            labels = labels.get(name, {})
        elif "mappings" in document:
            name = document.get("name", Path(path).stem)
            mappings = document["mappings"]
            labels = document.get("labels", {})
        else:
            name, mappings, labels = Path(path).stem, document, {}
        original_name = name
        name = cls._profile_name(name)
        if not isinstance(mappings, dict) or any(
                event not in VALID_EVENT_NAMES or resolve_action(action) is None
                for event, action in mappings.items()):
            raise ValueError("Profile contains malformed or unsupported assignments")
        if not isinstance(labels, dict) or any(
                event not in LABEL_EVENT_NAMES or not isinstance(value, str)
                for event, value in labels.items()):
            raise ValueError("Profile contains invalid labels")
        applications = document.get("applications", {}) if "profiles" in document or "mappings" in document else {}
        if not isinstance(applications, dict) or any(
                not isinstance(exe, str) or not exe.strip() or not isinstance(target, str)
                for exe, target in applications.items()):
            raise ValueError("Profile contains invalid application associations")
        if document.get("format") == PROFILE_FORMAT and any(target != original_name for target in applications.values()):
            raise ValueError("Exported profiles cannot reference other profiles")
        applications = {exe.lower(): name for exe, target in applications.items() if target == original_name}
        return name, mappings, labels, applications

    def import_profile(self, path, name=None):
        imported_name, mappings, labels, applications = self._read_profile_import(path)
        name = self._profile_name(name) if name is not None else imported_name
        def change(candidate):
            if name in candidate["profiles"]:
                raise ValueError("A profile with that name already exists")
            candidate["profiles"][name] = copy.deepcopy(mappings)
            for event, label in labels.items():
                self._set_label(candidate, name, event, label)
            if applications:
                existing = candidate.setdefault("applications", {})
                if not isinstance(existing, dict):
                    raise ValueError("Invalid applications metadata; refusing to overwrite it")
                # Import never silently redirects an existing application binding.
                bound = {exe.lower() for exe in existing if isinstance(exe, str)}
                for exe in applications:
                    if exe not in bound:
                        existing[exe] = name
        self._mutate(change)
        return name

    def export_profile(self, profile, path, overwrite=False):
        destination = Path(path)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Choose a file other than the live config.json")
        with self.lock:
            mappings = copy.deepcopy(self._editable_profile(self.data, profile))
            all_labels = self.data.get("labels", {})
            labels = copy.deepcopy(all_labels.get(profile, {})) if isinstance(all_labels, dict) else {}
            applications = {exe: profile for exe, target in self.compiled[2].items() if target == profile}
            for exe, target in APPLICATION_PROFILES.items():
                if target == profile and exe not in self.compiled[2]:
                    applications[exe] = profile
        if any(event not in VALID_EVENT_NAMES or resolve_action(action) is None for event, action in mappings.items()):
            raise ValueError("Profile contains unsupported assignments; export cancelled")
        if not isinstance(labels, dict) or any(event not in LABEL_EVENT_NAMES or not isinstance(label, str)
                                              for event, label in labels.items()):
            raise ValueError("Profile contains invalid labels; export cancelled")
        document = {"format": PROFILE_FORMAT, "name": profile, "mappings": mappings, "labels": labels}
        if applications:
            document["applications"] = applications
        contents = (json.dumps(document, indent=4, ensure_ascii=False) + "\n").encode("utf-8")
        previous = destination.read_bytes() if destination.exists() else None
        if previous is not None and not overwrite:
            raise ValueError("Export file already exists")
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".profile-", suffix=".tmp", delete=False) as output:
                temporary_path = Path(output.name)
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            current = destination.read_bytes() if destination.exists() else None
            if current != previous:
                raise ValueError("Export file changed outside the app; export cancelled")
            os.replace(temporary_path, destination)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return destination

    def _mutate(self, change, publish=None):
        # Serialize writers while keeping disk I/O off the serial reader's lock.
        with self.write_lock:
            if self.error:
                raise ValueError(self.error)
            with self.lock:
                candidate = copy.deepcopy(self.data)
            change(candidate)
            if self.path.read_bytes() != self.disk_bytes:
                raise ValueError("config.json changed outside the app; reopen before saving")
            if candidate == self.data:
                if publish is not None:
                    with self.lock:
                        publish()
                return False
            return self._write(candidate, publish)

    def _write(self, candidate, publish):
        compiled = compile_profiles(candidate)
        contents = (json.dumps(candidate, indent=4, ensure_ascii=False) + "\n").encode("utf-8")
        if self.path.read_bytes() != self.disk_bytes:
            raise ValueError("config.json changed outside the app; reopen before saving")
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix=".config-",
                                             suffix=".tmp", delete=False) as output:
                temporary_path = Path(output.name)
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            # A user may edit the file while the temporary write is in progress.
            if self.path.read_bytes() != self.disk_bytes:
                raise ValueError("config.json changed outside the app; reopen before saving")
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        # Disk I/O occurs outside this lock, keeping the serial reader responsive.
        with self.lock:
            self.data = candidate
            self.compiled = compiled
            self.disk_bytes = contents
            if publish is not None:
                publish()
        return True
