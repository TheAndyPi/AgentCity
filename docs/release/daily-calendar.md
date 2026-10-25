# Daily calendar and citizen routines

The calendar advances 12 game seconds per default one-second physical tick.
At 20 ticks per second, 30 game minutes take 7.5 real seconds and a day takes
six minutes. New worlds start at Day 1, 08:00. Legacy ten-second worlds use
a calendar step of 120 seconds at two ticks per second. Speed controls scale both
clocks and actions; movement, collisions, disaster damage and care retain their
physical timing. Economy rates and explicit scenario durations retain their units.

`SIM_PHYSICS_SECONDS_PER_REAL_SECOND=20` explicitly selects this baseline.
The legacy default `SIM_BASE_TICKS_PER_SECOND=2` is recognized as the original
two ten-second ticks per second, so existing local `.env` files keep the same
normal pace. The newer legacy value 20 also remains supported. Use the explicit
physical-rate setting for intentional custom rates, including a physical rate of 2.

Simulation responses add `calendar_time_seconds`; configuration adds
`calendar_seconds_per_tick`. Missing legacy calendar values fall back to elapsed
physical time. The first resumed tick records calendar rule activation version
3.0.0. Historical objects are never rewritten. Contract snapshot revision 4
includes these additive fields in HTTP, snapshots and mapless stream frames.

Citizens follow persistent visits and meals, return home around 21:00, and sleep
from approximately 22:00 to 06:00 with a stable personality offset. Homeward travel
uses legal paths and room reservations, with known shelters as a fallback.
Blocked routes have bounded retry pauses. Sleep remains distinct from medical
unconsciousness. Ordinary needs and recovery now use game-hour rates; physical
care and resource accounting remain conserved.

Accepted conversations occupy at least an hour, with alternating replies about
20 game minutes apart. Listeners remain present between replies and receive
benefits for elapsed contact time, without repeated dialogue or rewards per
frame. Danger, urgent needs, care and a known curfew can interrupt them. World
frames expose session status, deadlines and end reasons. The clock, conversation
panels, bubbles, activity labels and both world renderers consume that state.

The `set_curfew` scenario operation announces an enabled state, start/end minutes
and audience, defaulting to 22:00–06:00. Temporary operations expire and restore
earlier controls. Citizens make a seeded compliance decision per policy revision
and night, based on cooperation, institutional trust and risk tolerance. Decisions
produce memories, traces and compliance counters. Safety and medical needs have
priority. The interpreter requests a persistent policy when duration is omitted.

## Verification

- Backend calendar tests cover clock separation, walking, speaking turns,
  interruptions, contact rewards, sleep/wake, blocked/full/unsafe housing,
  meals, curfew scheduling/reversion, model relevance and legacy persistence.
- Three complete days pass for seeded populations 10, 30 and 100 with adequate
  supplies: citizens remain alive, eat, sleep and recover while remaining active
  during the day.
- Frontend unit tests cover clock fallback, phase boundaries, curfew windows,
  session bubbles and activity labels.
- `node node_modules/@playwright/test/cli.js test --config=playwright.calendar.config.ts`
  verifies day, dusk, night, dawn and curfew in both renderers with reduced motion.
  Screenshots are written under `backend/.tmp/calendar-playwright-results`.
- Standard checks are `npm test`, `npm run build`, backend `pytest`,
  `python -m scripts.contracts --check`, and Ruff check/format verification.
