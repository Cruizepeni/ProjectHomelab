from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

from TerminalSSUI import TerminalSSUI, TerminalCanvas, display_width
from TerminalSSProtocolText import header_value, parse_headers_and_sections


class TerminalSSDNAProtocol:
    PROTOCOL_ID = "DNA"
    KEY = "3"
    DEFAULT_SETTINGS = {
        "SpeciesAnalysisTime": 10.0,
        "GlitchChance": 10,
        "UnsuccessfulSpliceGlitchChance": 100,
        "SpliceAttemptRate": 10,
        "SpliceSuccessRate": 5,
        "Color": "Mint",
        "RGB": False,
        "RGBSpeed": 50,
        "CustomColorShift": False,
        "CustomColorShiftSpeed": 50,
        "CustomColorShiftColors": ["Mint", "Cyan", "White"],
    }
    SETTING_SCHEMA = {
        "SpeciesAnalysisTime": {"Label": "Species Analysis Time", "Type": "seconds", "Min": 1, "Max": 120},
        "GlitchChance": {"Label": "Glitch Rate", "Type": "percent"},
        "UnsuccessfulSpliceGlitchChance": {"Label": "Glitch Rate For Unsuccessful Splice", "Type": "percent"},
        "SpliceAttemptRate": {"Label": "Splice Attempt Rate", "Type": "percent"},
        "SpliceSuccessRate": {"Label": "Splice Success Rate", "Type": "percent"},
        "Color": {"Label": "Color", "Type": "color"},
        "RGB": {"Label": "RGB", "Type": "boolean"},
        "RGBSpeed": {"Label": "RGB Speed", "Type": "percent"},
        "CustomColorShift": {"Label": "Custom Color Shift", "Type": "boolean"},
        "CustomColorShiftSpeed": {"Label": "Custom Color Shift Speed", "Type": "percent"},
        "CustomColorShiftColors": {"Label": "Custom Color Shift Colors", "Type": "color_list"},
    }
    PROFILE_HOLD_TIME = 5.0
    SPLICE_RESULT_HOLD_TIME = 5.0
    FAILURE_GLITCH_TIME = 0.5
    ANALYSIS_FIELDS = (
        ("Species", ("Identity", "SpeciesName")),
        ("Scientific Name", ("Identity", "ScientificName")),
        ("Category", ("Identity", "SpeciesCategory")),
        ("Genetic Material", ("Biology", "GeneticMaterial")),
        ("Cellular Type", ("Biology", "CellularType")),
        ("Respiration", ("Biology", "Respiration")),
        ("Reproduction", ("Biology", "Reproduction")),
        ("Body Plan", ("Morphology", "BodyPlan")),
        ("Structural System", ("Morphology", "StructuralSystem")),
        ("Habitat", ("Ecology", "Habitat")),
        ("Chromosome Count", ("Genome", "ChromosomeCount")),
    )
    COMPATIBILITY_FIELDS = (
        (("Biology", "GeneticMaterial"), 18.0),
        (("Biology", "CellularType"), 16.0),
        (("Biology", "Reproduction"), 8.0),
        (("Biology", "Respiration"), 6.0),
        (("Morphology", "BodyPlan"), 8.0),
        (("Morphology", "StructuralSystem"), 8.0),
        (("Morphology", "Locomotion"), 5.0),
        (("Ecology", "EnvironmentalRange"), 5.0),
        (("Ecology", "Habitat"), 4.0),
        (("Identity", "SpeciesCategory"), 4.0),
    )

    @classmethod
    def settings_contract(cls) -> dict[str, Any]:
        return {"Defaults": cls.DEFAULT_SETTINGS, "Schema": cls.SETTING_SCHEMA}

    def __init__(self, asset_manager, ui: TerminalSSUI):
        self.asset_manager = asset_manager
        self.ui = ui
        self.asset_path = self.asset_manager.protocol_path(self.PROTOCOL_ID)
        self.characters: tuple[str, ...] = tuple("ATCG0123456789")
        self.profiles: list[dict[str, Any]] = []
        self.current_profile: dict[str, Any] | None = None
        self.secondary_profile: dict[str, Any] | None = None
        self.last_profile_path: Path | None = None
        self.phase = "analysis"
        self.phase_started = 0.0
        self.phase_ends = 0.0
        self.analysis_started = 0.0
        self.analysis_ends = 0.0
        self.glitch_at: float | None = None
        self.glitch_until = 0.0
        self.failure_glitch_pending = False
        self.failure_glitch_triggered = False
        self.splice_data: dict[str, Any] | None = None
        self.helix_phase_a = random.random() * math.tau
        self.helix_phase_b = random.random() * math.tau
        self.helix_direction_a = random.choice((-1, 1))
        self.helix_direction_b = random.choice((-1, 1))
        self.next_reverse_a = 0.0
        self.next_reverse_b = 0.0
        self.load_assets()

    def load_assets(self) -> None:
        pool = self.asset_manager.character_set("Curated DNA", "ATCG0123456789")
        unique = []
        seen = set()
        for token in pool:
            if token and token not in seen and display_width(token) == 1:
                seen.add(token)
                unique.append(token)
        if unique:
            self.characters = tuple(unique)
        self.profiles = []
        for root in self.asset_manager.protocol_asset_roots(self.PROTOCOL_ID):
            for path in sorted(root.rglob("*.txt")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                headers, sections = parse_headers_and_sections(text, ("Sequence", "GeneticBehaviour", "Art"))
                species_name = header_value(headers, "SpeciesName")
                if species_name == "Unknown" and not any(key.casefold().replace(" ", "") == "speciesname" for key in headers):
                    continue
                sequence_groups = sections.get("Sequence", [])
                behaviour_groups = sections.get("GeneticBehaviour", [])
                sequence = sequence_groups[0] if sequence_groups else ["Unknown"]
                behaviour = behaviour_groups[0] if behaviour_groups else ["Unknown"]
                sequence = [line for line in sequence if line.strip()] or ["Unknown"]
                behaviour = [line for line in behaviour if line.strip()] or ["Unknown"]
                profile = {
                    "Identity": {
                        "SpeciesName": species_name,
                        "ScientificName": header_value(headers, "ScientificName"),
                        "SpeciesCategory": header_value(headers, "SpeciesCategory"),
                    },
                    "Biology": {
                        "GeneticMaterial": header_value(headers, "GeneticMaterial"),
                        "CellularType": header_value(headers, "CellularType"),
                        "Respiration": header_value(headers, "Respiration"),
                        "Reproduction": header_value(headers, "Reproduction"),
                    },
                    "Morphology": {
                        "BodyPlan": header_value(headers, "BodyPlan"),
                        "StructuralSystem": header_value(headers, "StructuralSystem"),
                        "Locomotion": header_value(headers, "Locomotion"),
                    },
                    "Ecology": {
                        "Habitat": header_value(headers, "Habitat"),
                        "EnvironmentalRange": header_value(headers, "EnvironmentalRange"),
                    },
                    "Genome": {
                        "ChromosomeCount": header_value(headers, "ChromosomeCount"),
                        "Sequence": sequence,
                    },
                    "Traits": {
                        "GeneticBehaviour": behaviour,
                    },
                    "_Folder": path,
                    "_Art": [group for group in sections.get("Art", []) if any(line.strip() for line in group)],
                }
                self.profiles.append(profile)

    @staticmethod
    def _nested(profile: dict[str, Any] | None, path: tuple[str, str], default: Any = "Unknown") -> Any:
        if not isinstance(profile, dict):
            return default
        section = profile.get(path[0])
        if not isinstance(section, dict):
            return default
        value = section.get(path[1], default)
        if value is None or value == "":
            return default
        return value

    @staticmethod
    def _is_unknown(value: Any) -> bool:
        if value is None:
            return True
        text = str(value).strip().casefold()
        return text in {"", "unknown", "unavailable", "data unavailable", "n/a", "none"}

    @staticmethod
    def _tokens(value: Any) -> set[str]:
        text = str(value).casefold()
        cleaned = []
        for char in text:
            cleaned.append(char if char.isalnum() else " ")
        return {token for token in "".join(cleaned).split() if token not in {"unknown", "variable", "highly", "approximately"}}

    @classmethod
    def _similarity(cls, first: Any, second: Any) -> float | None:
        if cls._is_unknown(first) or cls._is_unknown(second):
            return None
        a = str(first).strip().casefold()
        b = str(second).strip().casefold()
        if a == b:
            return 1.0
        a_tokens = cls._tokens(first)
        b_tokens = cls._tokens(second)
        if not a_tokens or not b_tokens:
            return 0.0
        overlap = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        return overlap / union if union else 0.0

    @staticmethod
    def _genetic_behaviour(profile: dict[str, Any] | None) -> list[str]:
        if not isinstance(profile, dict):
            return []
        traits = profile.get("Traits")
        if not isinstance(traits, dict):
            return []
        values = traits.get("GeneticBehaviour", [])
        if isinstance(values, str):
            values = [values]
        return [str(value) for value in values if isinstance(value, str)] if isinstance(values, list) else []

    @classmethod
    def _behaviour_modifier(cls, profile: dict[str, Any] | None) -> float:
        text = " | ".join(cls._genetic_behaviour(profile)).casefold()
        score = 0.0
        if "assimilat" in text:
            score += 70.0
        if "adaptive" in text:
            score += 20.0
        if "highly mutable" in text:
            score += 15.0
        elif "mutable" in text:
            score += 8.0
        if "foreign dna rejection" in text or "foreign genetic rejection" in text:
            score -= 60.0
        if "genetically isolated" in text:
            score -= 40.0
        if "incompatible" in text:
            score -= 30.0
        return score

    @classmethod
    def _compatibility(cls, first: dict[str, Any], second: dict[str, Any]) -> dict[str, float]:
        weighted = 0.0
        weight_total = 0.0
        groups = {"Genome": [], "Cellular": [], "Structural": [], "Environmental": []}
        for path, weight in cls.COMPATIBILITY_FIELDS:
            similarity = cls._similarity(cls._nested(first, path), cls._nested(second, path))
            if similarity is None:
                continue
            weighted += similarity * weight
            weight_total += weight
            if path in (("Biology", "GeneticMaterial"), ("Biology", "Reproduction")):
                groups["Genome"].append(similarity)
            elif path in (("Biology", "CellularType"), ("Biology", "Respiration")):
                groups["Cellular"].append(similarity)
            elif path in (("Morphology", "BodyPlan"), ("Morphology", "StructuralSystem"), ("Morphology", "Locomotion")):
                groups["Structural"].append(similarity)
            elif path in (("Ecology", "EnvironmentalRange"), ("Ecology", "Habitat")):
                groups["Environmental"].append(similarity)
        overall = 50.0 if weight_total <= 0 else weighted / weight_total * 100.0
        result = {"Overall": overall}
        for name, values in groups.items():
            result[name] = sum(values) / len(values) * 100.0 if values else 50.0
        return result

    @classmethod
    def _splice_probability(cls, first: dict[str, Any], second: dict[str, Any], settings: dict) -> dict[str, Any]:
        compatibility = cls._compatibility(first, second)
        modifier_a = cls._behaviour_modifier(first)
        modifier_b = cls._behaviour_modifier(second)
        behaviour_modifier = modifier_a + modifier_b
        base = max(0.0, min(100.0, float(settings.get("SpliceSuccessRate", 5))))
        chance = base + (compatibility["Overall"] - 50.0) * 0.35 + behaviour_modifier
        chance = max(0.5, min(99.0, chance))
        rejection = max(1.0, min(99.0, 100.0 - compatibility["Cellular"] + max(0.0, -behaviour_modifier) * 0.35))
        adaptive = max(0.0, min(100.0, 50.0 + behaviour_modifier * 0.7))
        return {
            "Compatibility": compatibility,
            "BehaviourModifier": behaviour_modifier,
            "SuccessChance": chance,
            "RejectionRisk": rejection,
            "AdaptiveResponse": adaptive,
        }

    def _choose_profile(self, exclude: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.profiles:
            return None
        choices = [profile for profile in self.profiles if profile is not exclude]
        if self.last_profile_path is not None and len(choices) > 1:
            filtered = [profile for profile in choices if profile.get("_Folder") != self.last_profile_path]
            if filtered:
                choices = filtered
        if not choices:
            choices = self.profiles
        profile = random.choice(choices)
        return profile

    def _schedule_helix_reversals(self, now: float) -> None:
        self.next_reverse_a = now + random.uniform(5.0, 10.0)
        self.next_reverse_b = now + random.uniform(5.0, 10.0)

    def _update_helix_directions(self, now: float) -> None:
        if now >= self.next_reverse_a:
            self.helix_direction_a *= -1
            self.next_reverse_a = now + random.uniform(5.0, 10.0)
        if now >= self.next_reverse_b:
            self.helix_direction_b *= -1
            self.next_reverse_b = now + random.uniform(5.0, 10.0)

    def _schedule_general_glitch(self, settings: dict, start: float, duration: float) -> None:
        self.glitch_at = None
        chance = max(0, min(100, int(settings.get("GlitchChance", 10))))
        if duration > 0 and random.random() * 100 < chance:
            self.glitch_at = start + random.uniform(duration * 0.12, max(duration * 0.13, duration * 0.88))

    def _start_analysis(self, settings: dict, now: float, profile: dict[str, Any] | None = None) -> None:
        self.current_profile = profile or self._choose_profile()
        self.secondary_profile = None
        self.splice_data = None
        self.phase = "analysis"
        self.phase_started = now
        duration = max(1.0, float(settings.get("SpeciesAnalysisTime", 10.0)))
        self.analysis_started = now
        self.analysis_ends = now + duration
        self.phase_ends = self.analysis_ends + self.PROFILE_HOLD_TIME
        self.failure_glitch_pending = False
        self.failure_glitch_triggered = False
        self.glitch_until = 0.0
        if self.current_profile is not None:
            self.last_profile_path = self.current_profile.get("_Folder")
        self._schedule_helix_reversals(now)
        self._schedule_general_glitch(settings, now, duration)

    def _start_splice(self, settings: dict, now: float) -> bool:
        if self.current_profile is None or len(self.profiles) < 2:
            return False
        secondary = self._choose_profile(exclude=self.current_profile)
        if secondary is None or secondary is self.current_profile:
            return False
        self.secondary_profile = secondary
        self.splice_data = self._splice_probability(self.current_profile, secondary, settings)
        success_chance = float(self.splice_data["SuccessChance"])
        self.splice_data["Success"] = random.random() * 100 < success_chance
        self.splice_data["HybridSequence"] = self._hybrid_sequence(self.current_profile, secondary)
        self.splice_data["Dominant"] = self._dominant_species(self.current_profile, secondary)
        self.phase = "splice"
        self.phase_started = now
        duration = max(1.0, float(settings.get("SpeciesAnalysisTime", 10.0)))
        self.analysis_started = now
        self.analysis_ends = now + duration
        self.phase_ends = self.analysis_ends + self.SPLICE_RESULT_HOLD_TIME
        self.failure_glitch_pending = not bool(self.splice_data["Success"])
        self.failure_glitch_triggered = False
        self.glitch_until = 0.0
        self._schedule_helix_reversals(now)
        self._schedule_general_glitch(settings, now, duration)
        return True

    def reset(self, settings: dict, width: int, height: int, now: float | None = None) -> None:
        base = now if now is not None else time.monotonic()
        self.current_profile = None
        self.secondary_profile = None
        self.splice_data = None
        self.glitch_at = None
        self.glitch_until = 0.0
        self.helix_direction_a = random.choice((-1, 1))
        self.helix_direction_b = random.choice((-1, 1))
        self.helix_phase_a = random.random() * math.tau
        self.helix_phase_b = random.random() * math.tau
        self._start_analysis(settings, base)

    def _analysis_progress(self, now: float) -> float:
        duration = max(0.001, self.analysis_ends - self.analysis_started)
        return max(0.0, min(1.0, (now - self.analysis_started) / duration))

    @staticmethod
    def _analysis_completion(progress: float) -> int:
        return max(0, min(100, int(round(progress * 100.0))))

    def _decoded_field_value(self, value: Any, visible: bool, now: float, seed: int) -> str:
        target = str(value if value not in {None, ""} else "Unknown")
        if visible:
            return target
        rng = random.Random(seed ^ int(now * 9))
        output = []
        for char in target:
            if char.isspace() or not char.isalnum():
                output.append(char)
            else:
                output.append(rng.choice(self.characters))
        return "".join(output)

    def _analysis_values(self, profile: dict[str, Any], progress: float, now: float) -> list[tuple[str, str]]:
        values = []
        field_count = len(self.ANALYSIS_FIELDS)
        for index, (label, path) in enumerate(self.ANALYSIS_FIELDS):
            threshold = (index + 1) / (field_count + 1)
            visible = progress >= threshold
            value = self._nested(profile, path)
            display = self._decoded_field_value(value, visible, now, hash((label, str(profile.get("_Folder", "")))))
            values.append((label, display))
        return values

    @staticmethod
    def _sequences(profile: dict[str, Any] | None) -> list[str]:
        if not isinstance(profile, dict):
            return []
        genome = profile.get("Genome")
        if not isinstance(genome, dict):
            return []
        sequence = genome.get("Sequence", [])
        if isinstance(sequence, str):
            sequence = [sequence]
        if not isinstance(sequence, list):
            return []
        result = [str(line) for line in sequence if isinstance(line, str) and line.strip()]
        if not result or all(line.strip().casefold() == "unknown" for line in result):
            return []
        return result

    def _scramble_sequence(self, target: str, progress: float, now: float, seed: int) -> str:
        progress = max(0.0, min(1.0, progress))
        rng = random.Random(seed ^ int(now * 12))
        threshold = int(len(target) * progress)
        output = []
        for index, char in enumerate(target):
            if not char.isalnum() or index < threshold:
                output.append(char)
            else:
                output.append(rng.choice(self.characters))
        return "".join(output)

    @staticmethod
    def _profile_name(profile: dict[str, Any] | None) -> str:
        return str(TerminalSSDNAProtocol._nested(profile, ("Identity", "SpeciesName"), "Unknown"))

    @staticmethod
    def _chromosomes(profile: dict[str, Any] | None) -> str:
        return str(TerminalSSDNAProtocol._nested(profile, ("Genome", "ChromosomeCount"), "Unknown"))

    @staticmethod
    def _art_blocks(profile: dict[str, Any] | None) -> list[list[str]]:
        if not isinstance(profile, dict):
            return []
        values = profile.get("_Art", [])
        if not isinstance(values, list):
            return []
        return [[str(line) for line in block] for block in values if isinstance(block, list)]

    def _art_lines(self, profile: dict[str, Any] | None, progress: float, now: float) -> list[str]:
        blocks = self._art_blocks(profile)
        if not blocks:
            return []
        if progress < 1.0:
            index = min(len(blocks) - 1, int(progress * len(blocks)))
        else:
            index = int(now) % len(blocks)
        return list(blocks[index])

    def _helix_sequence(self, profile: dict[str, Any] | None) -> str:
        sequences = self._sequences(profile)
        combined = "".join(sequences)
        letters = "".join(char for char in combined.upper() if char.isalnum())
        return letters or "ATCGATCGATCGATCG"

    def _draw_helix(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, profile: dict[str, Any] | None, phase: float, direction: int, wide: bool = False) -> None:
        if width < 10 or height < 4:
            return
        center = x + width // 2
        if wide:
            amplitude = max(4, min(14, int(width * 0.23)))
            turn_step = 0.34
        else:
            amplitude = max(2, min(width // 3, 8))
            turn_step = 0.48
        sequence = self._helix_sequence(profile)
        pair_map = {"A": "T", "T": "A", "C": "G", "G": "C"}
        for row in range(height):
            angle = phase + direction * row * turn_step
            offset = int(round(math.sin(angle) * amplitude))
            left = center + offset
            right = center - offset
            first = sequence[row % len(sequence)].upper()
            second = pair_map.get(first, sequence[(row + 1) % len(sequence)].upper())
            depth = math.cos(angle)
            style_first = 3 if depth >= 0 else 1
            style_second = 1 if depth >= 0 else 3
            if left > right:
                left, right = right, left
                first, second = second, first
                style_first, style_second = style_second, style_first
            if right - left > 1:
                for column in range(left + 1, right):
                    canvas.put(column, y + row, "─" if row % 2 == 0 else "·", 1)
            canvas.put(left, y + row, first, style_first)
            canvas.put(right, y + row, second, style_second)

    def _draw_genetic_sequencer(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, now: float) -> None:
        canvas.panel(x, y, width, height, "GENETIC SEQUENCER", 2)
        inner_y = y + 2
        inner_h = max(1, height - 3)
        elapsed = max(0.0, now - self.phase_started)
        self.helix_phase_a += self.helix_direction_a * 0.045
        if self.phase == "splice" and self.secondary_profile is not None:
            split = max(10, (width - 3) // 2)
            self._draw_helix(canvas, x + 1, inner_y, split - 1, inner_h, self.current_profile, self.helix_phase_a + elapsed * 0.02, self.helix_direction_a)
            self.helix_phase_b += self.helix_direction_b * 0.045
            self._draw_helix(canvas, x + split + 1, inner_y, width - split - 2, inner_h, self.secondary_profile, self.helix_phase_b + elapsed * 0.02, self.helix_direction_b)
            canvas.text(x + 2, y + height - 2, "A", 3)
            canvas.text(x + width - 3, y + height - 2, "B", 3)
        else:
            self._draw_helix(canvas, x + 1, inner_y, width - 2, inner_h, self.current_profile, self.helix_phase_a + elapsed * 0.02, self.helix_direction_a, True)

    def _draw_species_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "SPECIES ANALYSIS", 2)
        if self.current_profile is None:
            canvas.centered_text(y + height // 2, "NO SPECIES PROFILES AVAILABLE", 3, x + 1, x + width - 1)
            return
        label_x = x + 2
        right = x + width - 2
        row = y + 2
        if row < y + height - 2:
            analyser_label = "SPECIES ANALYSER:"
            canvas.text(label_x, row, analyser_label, 2, max_width=max(1, width - 4))
            analyser_x = label_x + len(analyser_label) + 1
            analyser_w = max(1, right - analyser_x)
            seed = hash(str(self.current_profile.get("_Folder", "")))
            if now < self.glitch_until:
                analyser_state = "glitch"
                recovery = 0.0
            elif progress < 0.18:
                analyser_state = "recovery"
                recovery = progress / 0.18
            else:
                analyser_state = "normal"
                recovery = 1.0
            waveform = self.ui.analyser_trace(analyser_w, now, seed, analyser_state, recovery, 0.95)
            canvas.text(analyser_x, row, waveform, 2, max_width=analyser_w)
            row += 1
        rows = self._analysis_values(self.current_profile, progress, now)
        max_label = min(20, max((len(label) for label, _ in rows), default=0))
        available = max(8, width - max_label - 6)
        completion_y = y + height - 2
        for label, value in rows:
            if row >= completion_y:
                break
            canvas.text(x + 2, row, f"{label.upper()}:", 1, max_width=max_label + 1)
            canvas.text(x + max_label + 4, row, str(value), 3 if str(value).casefold() != "unknown" else 2, max_width=available)
            row += 1
        completion = self._analysis_completion(progress)
        if completion_y > y:
            completion_label = "ANALYSIS COMPLETION:"
            percent = f"{completion:3d}%"
            canvas.text(label_x, completion_y, completion_label, 1, max_width=max(1, width - 4))
            percent_x = max(label_x + len(completion_label) + 5, right - len(percent))
            bar_x = label_x + len(completion_label) + 1
            bar_w = max(3, percent_x - bar_x - 1)
            if bar_x < right:
                canvas.progress_bar(bar_x, completion_y, bar_w, completion, 3)
            canvas.text(percent_x, completion_y, percent, 3, max_width=max(1, right - percent_x + 1))

    def _draw_genome_sequence(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, profile: dict[str, Any] | None, progress: float, now: float, prefix: str = "") -> None:
        canvas.panel(x, y, width, height, "GENOME SEQUENCE", 2)
        if profile is None:
            return
        name = self._profile_name(profile)
        chromosomes = self._chromosomes(profile)
        canvas.text(x + 2, y + 2, f"{prefix + ': ' if prefix else ''}{name}", 3, max_width=max(1, width - 4))
        canvas.text(x + 2, y + 3, f"Chromosomes: {chromosomes}", 1, max_width=max(1, width - 4))
        sequences = self._sequences(profile)
        if not sequences:
            canvas.centered_text(y + max(4, height // 2), "SEQUENCE DATA UNAVAILABLE", 2, x + 1, x + width - 1)
            return
        row = y + 5
        max_rows = max(0, height - 6)
        for index, sequence in enumerate(sequences[:max_rows]):
            display = self._scramble_sequence(sequence, progress, now, hash((name, index)))
            canvas.text(x + 2, row + index, display, 2 if progress < 1 else 3, max_width=max(1, width - 4))

    def _draw_specimen_reconstruction(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, profile: dict[str, Any] | None, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "SPECIMEN RECONSTRUCTION", 2)
        lines = self._art_lines(profile, progress, now)
        if not lines:
            canvas.centered_text(y + max(2, height // 2 - 1), "DATABASE INCOMPLETE", 3, x + 1, x + width - 1)
            canvas.centered_text(y + max(3, height // 2 + 1), "NO SPECIMEN IMAGE AVAILABLE", 1, x + 1, x + width - 1)
            return
        visible = len(lines) if progress >= 1.0 else max(1, int(math.ceil(len(lines) * progress)))
        canvas.art(x + 1, y + 1, max(1, width - 2), max(1, height - 2), lines[:visible], 2 if progress < 1 else 3, True, True)

    @classmethod
    def _hybrid_sequence(cls, first: dict[str, Any], second: dict[str, Any]) -> list[str]:
        a = cls._sequences(first)
        b = cls._sequences(second)
        if not a and not b:
            return []
        if not a:
            return b[:3]
        if not b:
            return a[:3]
        count = max(1, min(3, max(len(a), len(b))))
        result = []
        for index in range(count):
            first_line = a[index % len(a)]
            second_line = b[index % len(b)]
            length = max(len(first_line), len(second_line))
            chars = []
            for position in range(length):
                use_first = position % 2 == 0
                source = first_line if use_first else second_line
                fallback = second_line if use_first else first_line
                if position < len(source):
                    chars.append(source[position])
                elif position < len(fallback):
                    chars.append(fallback[position])
            result.append("".join(chars))
        return result

    @classmethod
    def _dominant_species(cls, first: dict[str, Any], second: dict[str, Any]) -> str:
        first_modifier = cls._behaviour_modifier(first)
        second_modifier = cls._behaviour_modifier(second)
        if first_modifier == second_modifier:
            return random.choice((cls._profile_name(first), cls._profile_name(second)))
        return cls._profile_name(first if first_modifier > second_modifier else second)

    def _draw_splice_analysis(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "SPECIES SPLICE ATTEMPT", 2)
        if self.current_profile is None or self.secondary_profile is None or not isinstance(self.splice_data, dict):
            return
        compatibility = self.splice_data["Compatibility"]
        success = bool(self.splice_data["Success"])
        completed = progress >= 1.0
        values = [
            ("Primary Species", self._profile_name(self.current_profile)),
            ("Secondary Species", self._profile_name(self.secondary_profile)),
            ("Genome Match", f"{compatibility['Genome']:.0f}%"),
            ("Cellular Match", f"{compatibility['Cellular']:.0f}%"),
            ("Structural Match", f"{compatibility['Structural']:.0f}%"),
            ("Environmental Match", f"{compatibility['Environmental']:.0f}%"),
            ("Adaptive Response", f"{self.splice_data['AdaptiveResponse']:.0f}%"),
            ("Rejection Risk", f"{self.splice_data['RejectionRisk']:.0f}%"),
            ("Predicted Viability", f"{self.splice_data['SuccessChance']:.1f}%"),
            ("Dominant Genome", str(self.splice_data["Dominant"])),
        ]
        visible_count = max(2, int(math.ceil(len(values) * min(1.0, progress))))
        row = y + 2
        label_width = min(22, max(len(label) for label, _ in values) + 1)
        value_x = x + 2 + label_width + 1
        value_width = max(4, x + width - 2 - value_x)
        for index, (label, value) in enumerate(values):
            if row >= y + height - 4:
                break
            display = value if index < visible_count else "ANALYSING..."
            canvas.text(x + 2, row, f"{label}:", 1, max_width=label_width)
            canvas.text(value_x, row, display, 3 if index < visible_count else 2, max_width=value_width)
            row += 1
        analyser_y = y + height - 4
        if analyser_y > y + 1:
            analyser_label = "SPLICE ANALYSER:"
            analyser_x = x + 2
            canvas.text(analyser_x, analyser_y, analyser_label, 2, max_width=max(1, width - 4))
            trace_x = analyser_x + len(analyser_label) + 1
            trace_w = max(1, x + width - 2 - trace_x)
            if completed and not success:
                analyser_state = "failed"
                recovery = 0.0
            elif now < self.glitch_until:
                analyser_state = "glitch"
                recovery = 0.0
            elif progress < 0.16:
                analyser_state = "recovery"
                recovery = progress / 0.16
            else:
                analyser_state = "normal"
                recovery = 1.0
            seed = hash((self._profile_name(self.current_profile), self._profile_name(self.secondary_profile)))
            trace = self.ui.analyser_trace(trace_w, now, seed, analyser_state, recovery, 1.1)
            canvas.text(trace_x, analyser_y, trace, 2 if analyser_state != "failed" else 4, max_width=trace_w)
        status_y = y + height - 3
        if completed:
            if success:
                canvas.centered_text(status_y, "SPLICE VIABLE — HYBRID SEQUENCE STABLE", 4, x + 1, x + width - 1)
            elif not self.failure_glitch_pending and now >= self.glitch_until:
                canvas.centered_text(status_y, "SPLICE FAILED — RECOMBINATION ABORTED", 4, x + 1, x + width - 1)
            else:
                canvas.centered_text(status_y, "STABILISING RECOMBINANT GENOME...", 3, x + 1, x + width - 1)
        else:
            canvas.centered_text(status_y, "RECOMBINING...", 3, x + 1, x + width - 1)
        canvas.progress_bar(x + 2, y + height - 2, max(1, width - 4), progress * 100.0, 3)

    def _draw_splice_genome(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float, now: float) -> None:
        canvas.panel(x, y, width, height, "GENOME SEQUENCE", 2)
        if self.current_profile is None or self.secondary_profile is None or not isinstance(self.splice_data, dict):
            return
        a = self._sequences(self.current_profile)
        b = self._sequences(self.secondary_profile)
        hybrid = self.splice_data.get("HybridSequence", [])
        rows = [
            ("A", a[0] if a else "DATA UNAVAILABLE"),
            ("B", b[0] if b else "DATA UNAVAILABLE"),
            ("MIX", hybrid[0] if isinstance(hybrid, list) and hybrid else "MODEL UNAVAILABLE"),
        ]
        for index, (label, sequence) in enumerate(rows):
            row = y + 2 + index * 2
            if row >= y + height - 1:
                break
            canvas.text(x + 2, row, f"{label}:", 1)
            if label == "MIX" and "UNAVAILABLE" not in sequence:
                display = self._scramble_sequence(sequence, progress, now, hash((label, sequence)))
            else:
                display = sequence
            canvas.text(x + 7, row, display, 3 if label == "MIX" and progress >= 1 else 2, max_width=max(1, width - 9))

    def _draw_splice_reconstruction(self, canvas: TerminalCanvas, x: int, y: int, width: int, height: int, progress: float) -> None:
        canvas.panel(x, y, width, height, "SPECIMEN RECONSTRUCTION", 2)
        if not isinstance(self.splice_data, dict):
            return
        if progress < 1.0:
            canvas.centered_text(y + max(2, height // 2 - 1), "SYNTHETIC MORPHOLOGY MODEL", 3, x + 1, x + width - 1)
            canvas.centered_text(y + max(3, height // 2 + 1), f"RECONSTRUCTION {int(progress * 100):02d}%", 2, x + 1, x + width - 1)
            return
        if self.splice_data.get("Success"):
            canvas.centered_text(y + max(2, height // 2 - 2), "HYBRID MORPHOLOGY", 3, x + 1, x + width - 1)
            canvas.centered_text(y + max(3, height // 2), "NO REFERENCE IMAGE AVAILABLE", 1, x + 1, x + width - 1)
            canvas.centered_text(y + max(4, height // 2 + 2), "SYNTHETIC MODEL INCOMPLETE", 2, x + 1, x + width - 1)
        else:
            canvas.centered_text(y + max(2, height // 2 - 1), "MODEL COLLAPSED", 4, x + 1, x + width - 1)
            canvas.centered_text(y + max(3, height // 2 + 1), "VIABLE MORPHOLOGY NOT RECOVERED", 1, x + 1, x + width - 1)

    def _draw_layout(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        canvas = self.ui.canvas(width, height)
        if width < 70 or height < 22:
            canvas.overlay_center_box("DNA PROTOCOL", ["TERMINAL TOO SMALL", "Resize to at least 70 x 22", "Falling back to status view"])
            return canvas
        self._update_helix_directions(now)
        progress = self._analysis_progress(now)
        left_width = width // 2
        right_width = width - left_width
        self._draw_genetic_sequencer(canvas, 0, 0, left_width, height, now)
        if self.phase == "splice":
            preferred_analysis = 16
            analysis_height = min(preferred_analysis, max(10, height - 8))
            reconstruction_height = max(1, height - analysis_height)
            self._draw_splice_analysis(canvas, left_width, 0, right_width, analysis_height, progress, now)
            self._draw_splice_reconstruction(canvas, left_width, analysis_height, right_width, reconstruction_height, progress)
        else:
            preferred_analysis = len(self.ANALYSIS_FIELDS) + 5
            analysis_height = min(preferred_analysis, max(10, height - 8))
            reconstruction_height = max(1, height - analysis_height)
            self._draw_species_analysis(canvas, left_width, 0, right_width, analysis_height, progress, now)
            self._draw_specimen_reconstruction(canvas, left_width, analysis_height, right_width, reconstruction_height, self.current_profile, progress, now)
        return canvas

    def _advance_state(self, settings: dict, now: float) -> None:
        if self.current_profile is None:
            self._start_analysis(settings, now)
            return
        progress = self._analysis_progress(now)
        if self.phase == "splice" and progress >= 1.0 and isinstance(self.splice_data, dict) and not self.splice_data.get("Success"):
            if self.failure_glitch_pending and not self.failure_glitch_triggered:
                chance = max(0, min(100, int(settings.get("UnsuccessfulSpliceGlitchChance", 100))))
                self.failure_glitch_pending = False
                if random.random() * 100 < chance:
                    self.glitch_until = max(self.glitch_until, now + self.FAILURE_GLITCH_TIME)
                    self.failure_glitch_triggered = True
        if now < self.phase_ends:
            return
        if self.phase == "analysis":
            chance = max(0, min(100, int(settings.get("SpliceAttemptRate", 10))))
            if random.random() * 100 < chance and self._start_splice(settings, now):
                return
        self._start_analysis(settings, now)

    def render(self, width: int, height: int, settings: dict, now: float) -> TerminalCanvas:
        self._advance_state(settings, now)
        canvas = self._draw_layout(width, height, settings, now)
        if self.glitch_at is not None and now >= self.glitch_at and self.glitch_until <= now:
            self.glitch_until = now + random.uniform(0.22, 0.7)
            self.glitch_at = None
        if now < self.glitch_until:
            self.ui.apply_glitch(canvas, self.characters, 0.18, int(now * 20))
        return canvas

    def handle_runtime_key(self, key: str, settings: dict) -> bool:
        if key in {"+", "="}:
            settings["SpeciesAnalysisTime"] = max(1.0, float(settings.get("SpeciesAnalysisTime", 10.0)) - 1.0)
            return True
        if key in {"-", "_"}:
            settings["SpeciesAnalysisTime"] = min(120.0, float(settings.get("SpeciesAnalysisTime", 10.0)) + 1.0)
            return True
        if key == "BACKSPACE":
            self.reverse_direction(settings)
            return True
        return False

    def reverse_direction(self, settings: dict) -> None:
        self.helix_direction_a *= -1
        self.helix_direction_b *= -1
        now = time.monotonic()
        self._schedule_helix_reversals(now)

    def primary_speed_label(self, settings: dict) -> str:
        return f"Species Analysis Time {float(settings.get('SpeciesAnalysisTime', 10.0)):g}s"


PROTOCOL_CLASS = TerminalSSDNAProtocol
