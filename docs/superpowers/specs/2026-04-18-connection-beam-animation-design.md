# Connection Beam Animation

**Date:** 2026-04-18
**File:** `game/networked_board.py` — `_run_waiting_animation()`

## Summary

Replace the single-beam waiting loop with a three-phase animation that celebrates a successful network connection: the original cyan beam spawns an orange counter-beam on connection, the two beams ease-in accelerate to collide on the opposite side of the board, a bright white flash fills the board on impact, and an energetic shockwave explodes outward from the collision point revealing the full-brightness game-ready checkerboard.

## Phases

### Phase 1: CHASE (existing, unchanged)

- Single cyan `(64, 255, 255)` beam with 6-cell quadratic-fading tail traces the 28-cell perimeter path.
- Background: dim checkerboard (shades 12 and 6).
- Step interval: 0.06s.
- Runs while `self._peer_name is None`.

### Phase 2: CONVERGE

**Trigger:** `_peer_name` becomes non-None (hello message received).

- Record current beam index as `spawn_pos`.
- Collision target: `(spawn_pos + n // 2) % n` — diametrically opposite on the perimeter.
- Spawn an **orange** `(255, 160, 0)` counter-beam at `spawn_pos` traveling in reverse.
- Original cyan beam continues forward.
- **Quadratic ease-in**: `progress = t^2` where `t = elapsed / 0.9s`. Both beams start slow and accelerate into the collision.
- Frame interval: 0.02s (smooth motion).
- Duration: ~0.9s.

### Phase 3: FLASH + EXPLODE

**Trigger:** Both beams arrive at the collision point.

**Flash** (0.15s):
- Full-board white flash with quadratic brightness falloff over 5 frames.
- Every cell lit to `(255, 255, 255)` at peak, fading to black.

**Shockwave**:
- Collision cell becomes the origin.
- Euclidean distance (rounder wavefront) from collision for each cell.
- Radius expands at 14 cells/sec.
- Four zones per frame:
  - **Ahead of wavefront**: dim checkerboard background.
  - **Primary wavefront** (2.5 cells wide): hot white core with sin-curve intensity for a bell-shaped brightness profile.
  - **Afterglow** (1.5 cells trailing): warm orange fade `(180, 100, 50)` at peak, trailing the front.
  - **Behind everything**: revealed game-ready checkerboard.
- Frame interval: 0.025s.

## Colors

| Element | RGB |
|---------|-----|
| Cyan beam | `(64, 255, 255)` |
| Orange counter-beam | `(255, 160, 0)` |
| Dim checkerboard (light) | `(12, 12, 12)` |
| Dim checkerboard (dark) | `(6, 6, 6)` |
| Impact flash | `(255, 255, 255)` |
| Wavefront core | `(255, 255, 240)` (bell-curve intensity) |
| Afterglow | `(180, 100, 50)` at peak |
| Game-ready checkerboard | `theme_checker_color` or `(255, 255, 255)` |

## Timing

| Phase | Duration |
|-------|----------|
| CHASE | Until connection (~indefinite) |
| CONVERGE | ~0.9s (quadratic ease-in) |
| FLASH | ~0.15s |
| EXPLODE | ~0.8s (radius covers full diagonal) |
| **Total post-connection** | **~1.85s** |

## Scope

- Only `_run_waiting_animation()` in `game/networked_board.py` is modified.
- No new files. No protocol changes. No simulator changes.
