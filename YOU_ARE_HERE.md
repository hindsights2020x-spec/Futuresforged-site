# YOU ARE HERE — FuturesForged, in plain terms

A standing map of what you actually run, so anyone (you, Claude, or a Cowork
session) can get oriented in two minutes. You don't need to read the code — you
need to know which **room** the noise is coming from.

_Last updated: 2026-08-17._

---

## What you run (the plant tour)

You own a small **automated trading operation** across two computers and a cloud
database. Five parts:

**1. The Brain — `bot_engine.py` — Linux box, port 7331**
Watches the live market feed, runs your strategies (box mean-reversion,
sweep-reverse, momentum, L2), decides when there's a trade ("a signal"), and
enforces prop-firm rules (daily loss, contract limits). The trader who calls the
shots.

**2. The Hands — `copier_engine.py` — Linux box, port 7332**
Takes an order — from the Brain's signal, from *you* clicking Buy/Sell in Chart
Studio, or from a TradingView alert — and places it on your broker account(s),
copying to follower accounts scaled by a ratio. *(This is the piece we fixed so it
understands the Buy/Sell + MKT/LMT/STP the buttons actually send.)*

**3. The Long Arm to Windows — `ninjatrader_connector.py` (Linux) ⟷ `FuturesForgedBridge.cs` (Windows)**
Some accounts trade through **NinjaTrader**, which only runs on the Windows box.
For those, the Hands reach across a private **Tailscale** link to Windows, and
NinjaTrader submits the order to the broker. The bridge is the receiver on the
Windows side (it also streams fills + prices back).

**4. The Notice Board — Supabase (cloud database)**
The Brain constantly posts: signals, price candles, order book, open positions,
and now **health** (the heartbeat). The website, Chart Studio, and Claude all read
from here. It's how anything off the machines knows what's happening.

**5. The Face — Chart Studio & dashboards (the HTML pages)**
What you look at and click. Reads prices/positions from the Notice Board; sends
your clicks to the Hands.

**The two machines:** the **Linux box** (`ff-bot-prod`) runs Brain + Hands; the
**Windows box** runs NinjaTrader + the bridge. They talk over Tailscale only.

```
   YOU click ──► Face (Chart Studio) ──► Hands (copier :7332) ──► broker
                       ▲                        │  └─(NT accounts)─► Long Arm ─► NinjaTrader (Windows) ─► broker
                       │                        ▼
   Brain (:7331) ──► Notice Board (Supabase) ◄─┘   heartbeat ─► Notice Board (health)
   watches market,        ▲
   makes signals ─────────┘
```

---

## The map: "something's wrong" → which room

| What you'd notice | Which room | What it usually means / where to look |
|---|---|---|
| **Manual Buy/Sell did nothing** (screen said "submitted") | Hands (copier :7332) | Order reached the copier but didn't execute — copier log / `/api/place_order`. (The class we fixed.) |
| **Buy went in as a Sell**, or wrong size | Hands — `execute_order` / `copy_trade` | Direction/size translation. Covered by the fix; if it recurs, this is the room. |
| **Chart price frozen / lagging** | Notice Board, or the Windows price feed | Chart reads Supabase; NT price comes via the bridge's warm-worker (`ReadPrice`). A frozen NT symbol → Windows side. |
| **Bot isn't taking any trades** | Brain (:7331) | No signals firing, prop-rule/`can_trade` blocking, or the market feed dropped. Check `bot_engine` log + last signal time. |
| **Position isn't managing itself** (stop didn't move to breakeven) | Long Arm — FILL events | The bridge must push `FILL` on every position change; if those stop, trade management goes blind. |
| **"Is it even running?"** | Heartbeat / Notice Board | Query the `bot_health` table — both services should show `up` within the last minute. |
| **A NinjaTrader account won't trade** | Windows box + bridge | Is NinjaTrader open + logged in? AddOn compiled? Tailscale link up? |
| **Website shows stale / seeded data** | Notice Board pushers | `retail_feed_push` / `retail_mirror` on Linux stopped posting to Supabase. |

**How to use it:** don't diagnose — **localize.** Notice the symptom, find the row,
and say "it's the Hands" or "it's the Windows arm." That's the whole skill: know
which room the noise is in. Claude/Cowork takes it from there.

---

## Quick health check (anytime)
```sql
-- Are both services alive right now?
select service, up, git_sha, open_positions, ts from bot_health_latest;
```
Both rows `up = true` with a recent `ts` = the machine is green.

## The two boxes & ports at a glance
| Box | Runs | Ports |
|---|---|---|
| Linux `ff-bot-prod` | Brain (`bot_engine.py`), Hands (`copier_engine.py`), connectors, Supabase pushers, heartbeat | 7331 (brain), 7332 (copier) |
| Windows | NinjaTrader 8 + `FuturesForgedBridge.cs` | Tailscale-only listener (NT bridge) |
| Cloud | Supabase (`osxwkgmjwtdyvqwlfyre`): signals, bars, l2_book, positions, bot_health | — |
