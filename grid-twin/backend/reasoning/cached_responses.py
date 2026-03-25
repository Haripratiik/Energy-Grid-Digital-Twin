"""
Cached Reasoning Responses
==========================
Pre-authored operator advisories used in demo / offline mode so the front-end
can render realistic GRID-AI output without requiring a live LLM call.
"""

DEMO_CASCADE_RESPONSE = """SITUATION
Lines 5-6 and 8-9 are simultaneously overloaded at 97% and 84% of thermal limits following the trip of line 6-7. Generator 3 at Bus 3 is losing synchronism with the system reference.

IMMEDIATE ACTIONS
1. Shed 40 MW of interruptible load at Bus 5 to relieve overload on line 5-6.
2. Dispatch spinning reserve from Generator 1 — increase mechanical power setpoint to 265 MW to arrest frequency decline.
3. Arm bus protection relay at Substation C for islanding if Generator 3 rotor angle exceeds 75 degrees within the next 8 seconds.

RISK ASSESSMENT
Probability of cascading failure is 73% within 12 seconds absent load shedding; islanding of Generator 3 will follow angle instability."""
