# 6. Derived climate metrics: computed from the samples, not stored

- Status: accepted
- Date: 2026-11-04

## Context

The dashboard showed temperature and relative humidity and compared them with the
outdoor values. Two of its conclusions were misleading:

- "Indoor minus outdoor" in percentage points of relative humidity. On 2026-11-04
  the bedroom had 61 % at 22 °C and the outdoor air 71 % at 5.6 °C: the chart said
  the room was drier than outside, while it held 11.9 g/m³ of water against 5.0.
- A fixed 60 % limit as mould indicator. Mould grows on cold surfaces, so the same
  room humidity is harmless on a mild day and critical on a frosty one.

Wanted on top: detected airing and how long a room needs to get warm again, time
in the target range, heating degree days, more outdoor data, a weekly report and
the mould risk in Apple Home.

## Decision

- **Absolute humidity** (Magnus formula) is computed per sample in SQL through a
  Python function registered on the connection, so all existing aggregations get
  it for free. Indoor and outdoor are compared in g/m³.
- **Mould risk** uses the temperature factor fRsi of DIN 4108-2 to estimate the
  coldest wall temperature from the room and outdoor temperature, and the relative
  humidity there (limits 70 % and 80 %). The factor is a per-room setting with the
  standard's minimum of 0.7 as default.
- **Airing** is detected from the stored 5-minute samples (≥ 1 K drop and ≥ 0.8 g/m³
  less water within 15 minutes) instead of live in the bridge: it can be tuned and
  re-run over the whole history, and needs no state.
- **Daily statistics** are computed on request in one pass over the samples and
  cached in memory per completed day; the past year is precomputed in the
  background when the bridge starts (a few seconds on a Raspberry Pi 3). Nothing
  derived is written to the database, so a changed target or wall factor applies
  to the whole history after a restart.
- **More outdoor data**: solar radiation, wind and precipitation (stored as a rate,
  independent of the fetch interval) in new columns of the readings table, schema
  version 3.
- **Apple Home** gets the wall humidity as the standard `AirQuality` characteristic
  of each thermometer, because HomeKit has no mould or "air the room" service.

## Consequences

- The rules are heuristics with documented limits (heating season only for airing,
  an assumed wall factor). They are pure functions with tests based on the real
  readings of 2026-11-04.
- Restarting the bridge recomputes the cache; a request during warm-up takes a few
  seconds on a Pi 3.
- The API grows (`/api/daily`, more fields), but stays read-only.
