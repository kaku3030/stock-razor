# US Radar Options Context V0.1

Status: RESEARCH_ONLY / CONTEXT_ONLY / LIVE_TRADE=NO

## Purpose

Attach already-qualified US options/GEX evidence to Stock Radar V2 without
turning options intelligence into a signal or execution authority.

## Boundary

The adapter performs no provider I/O.

OptionsIntelligencePacket -> RadarOptionsContext -> Canonical US Radar output

It does not modify:

- canonical market data
- technical-state calculation
- signal permission
- risk budget
- order intent
- paper/live execution

A missing or BLOCKED options packet must not block the underlying price Radar.

## Context fields

- options regime under the declared GEX sign assumption
- net GEX
- gamma flip + model status
- call wall / put wall
- 0DTE concentration
- freshness status
- three-clock status
- GEX/profile completeness
- UNKNOWN fields and warnings

Every context payload keeps:

- price_acceptance_required=true
- decision_permission=BLOCKED_V0_1
- trading_authority=false
- live_trade=false

## Runtime wiring

V0.1 adds an optional evaluator input only. The stateful cloud worker does not
yet open an options provider or independently poll options data.

A later runtime step may consume an isolated persisted options evidence file.
That step must preserve independent sequencing/currentness so an options update
cannot be hidden by an unchanged canonical-bar sequence.
