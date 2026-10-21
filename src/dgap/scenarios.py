"""Scenario loading, canary generation, prompt assembly."""
from __future__ import annotations

import random
import string
from functools import lru_cache

import yaml

from . import CONFIGS

SCENARIOS = ("secret", "forbidden_tool")


@lru_cache(maxsize=None)
def load_scenario(name: str) -> dict:
    return yaml.safe_load(open(CONFIGS / "scenarios" / f"{name}.yaml", encoding="utf-8"))


@lru_cache(maxsize=1)
def load_pressure() -> dict:
    return yaml.safe_load(open(CONFIGS / "pressure.yaml", encoding="utf-8"))


@lru_cache(maxsize=1)
def load_protocols() -> dict:
    return yaml.safe_load(open(CONFIGS / "protocols.yaml", encoding="utf-8"))


def make_canary(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits
    return "dpl_" + "".join(rng.choice(alphabet) for _ in range(28))


def build_system_prompt(scenario: str, kpi: str = "none") -> str:
    prompt = load_scenario(scenario)["system_prompt"]
    if kpi == "kpi":
        prompt += "\n\n" + load_pressure()["kpi_note"]
    return prompt


def user_message(scenario: str, task_variant: str) -> str:
    return load_scenario(scenario)["user_messages"][task_variant]


def preset_messages(scenario: str, preset: str) -> list[str]:
    return list(load_pressure()["presets"][scenario][preset])


def resolve_preset(scenario: str, preset: str | None) -> str:
    """`preset` may be explicit (esc_*) or None -> calibrated choice from pressure.yaml."""
    if preset:
        return preset
    sel = load_pressure()["selected"].get(scenario)
    if not sel:
        raise ValueError(f"pressure preset for {scenario} not calibrated; set `selected` in pressure.yaml")
    return sel


def request_suffix(request: str) -> str:
    return "\n\n" + load_pressure()["request_suffix"] if request == "request" else ""
