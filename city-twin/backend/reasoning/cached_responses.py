"""Pre-cached demo responses for the reasoning layer.

Used in demo mode and as fallback when the LLM API is unavailable.
"""

DEMO_HEADLINE = (
    "Frequency dropping — two 132kV lines near thermal limits after transformer trip."
)

DEMO_WHAT_CHANGED: list[str] = [
    "Frequency at 59.72 Hz (−0.28 Hz deviation)",
    "Line L-12 at 92% thermal limit, Line L-15 at 84%",
    "Transformer T-3 tripped at Substation North",
    "Generator Bus 3 (gas) ramping to compensate, approaching limits",
]

DEMO_CASCADE_RESPONSE_TEXT = """\
SITUATION
Multiple transmission lines in the 132kV sub-transmission network are \
approaching thermal limits following the trip of transformer T-3 at \
Substation North. Generator 3 (gas combined-cycle at Bus 3) is compensating \
but approaching ramp limits. System frequency has dropped to 59.72 Hz.

IMMEDIATE ACTIONS
1. Shed 60 MW of interruptible industrial load at Bus 14 and Bus 16 to \
relieve overload on lines L-12 and L-15.
2. Increase Generator 2 (hydro at Bus 2) setpoint to 380 MW — fast governor \
response will arrest frequency decline within 4 seconds.
3. Dispatch Gas Peaker 1 at Bus 8 from 90 MW to 120 MW capacity to provide \
spinning reserve.

RISK ASSESSMENT
Probability of cascading failure is 61% within 20 seconds absent load \
shedding; thermal overload on L-12 will trigger protection relay in \
approximately 15 seconds at current loading."""

DEMO_PROPOSED_ACTIONS: list[dict] = [
    {
        "action_type": "LOAD_SHED",
        "target_rid": "ri.city-grid.main.load-bus.14",
        "parameters": {"delta_mw": -35},
        "rationale": (
            "Shed 35 MW interruptible industrial load at Bus 14 to relieve "
            "thermal overload on line L-12 in the 132kV sub-transmission ring."
        ),
        "confidence": 0.88,
        "estimated_impact_mw": -35,
        "reversible": True,
    },
    {
        "action_type": "LOAD_SHED",
        "target_rid": "ri.city-grid.main.load-bus.16",
        "parameters": {"delta_mw": -25},
        "rationale": (
            "Shed 25 MW at Bus 16 to reduce loading on line L-15 "
            "below 80% threshold."
        ),
        "confidence": 0.85,
        "estimated_impact_mw": -25,
        "reversible": True,
    },
    {
        "action_type": "GEN_SETPOINT",
        "target_rid": "ri.city-grid.main.generator.2",
        "parameters": {"target_mw": 380},
        "rationale": (
            "Increase hydro generator at Bus 2 from 300 MW to 380 MW. "
            "Fast governor response will arrest frequency decline."
        ),
        "confidence": 0.92,
        "estimated_impact_mw": 80,
        "reversible": True,
    },
    {
        "action_type": "GEN_SETPOINT",
        "target_rid": "ri.city-grid.main.generator.8",
        "parameters": {"target_mw": 120},
        "rationale": (
            "Dispatch Gas Peaker 1 to full 120 MW capacity "
            "for spinning reserve."
        ),
        "confidence": 0.90,
        "estimated_impact_mw": 30,
        "reversible": True,
    },
]

# A deliberately risky first proposal, used by the scripted demo to show the
# physics verifier veto the AI and the AI then self-correct. Opening line 26
# overloads the 132kV ring (see tests/test_safety_verifier.py).
DEMO_RISKY_ACTION: dict = {
    "action_type": "LINE_SWITCH",
    "target_rid": "ri.city-grid.main.transmission-line.26",
    "parameters": {"switch_open": True},
    "rationale": "Open line 26 to isolate the overloaded corridor and stop the cascade.",
    "confidence": 0.74,
    "estimated_impact_mw": 0.0,
    "reversible": False,
}

# The safe alternative the model returns after the verifier rejects the above.
# Sheds the load that was spiked onto the stressed corridor — a remedy that
# actually lowers the overload (NOT a setpoint on the slack bus, whose MW the
# power flow ignores, which would be a physical no-op the verifier rubber-stamps).
DEMO_CORRECTED_ACTION: dict = {
    "action_type": "LOAD_SHED",
    "target_rid": "ri.city-grid.main.load-bus.14",
    "parameters": {"delta_mw": -45.0},
    "rationale": ("Shed 45 MW of interruptible load at Bus 14 to relieve the overloaded "
                  "corridor — keeps every line in service instead of opening one."),
    "confidence": 0.86,
    "estimated_impact_mw": -45.0,
    "reversible": True,
}
