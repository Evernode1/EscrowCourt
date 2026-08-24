# EscrowCourt

A milestone-based freelance escrow arbitrated by **GenLayer Intelligent Contracts**. A buyer funds work in discrete milestones. A freelancer delivers and submits proof of each one. GenLayer's AI validators independently review the deliverable against the agreed requirement — and if either side disagrees with that review, a single formal dispute round gets one final, binding AI ruling.

## Architecture — 2 contracts, no server-side wallet

- **`contracts/registry.py`** — a single, permanent contract that indexes every deal for browsing (by status, by party). Deal contracts register themselves here once funded.
- **`contracts/deal.py`** — one contract per deal, holding that deal's milestones, funds, and dispute state. **Deployed directly from the buyer's own wallet in the browser** — the backend serves the contract's source code as plain text and never deploys anything itself.

This removes the server-side wallet entirely from the architecture: there is no `PRIVATE_KEY` anywhere in this project, no deploy-timeout risk on the backend, and no server-managed nonce to desync.

## Milestone state machine

```
pending → submitted → approved → paid
                    ↘ rejected → (resubmit → submitted)
                              ↘ (dispute evidence + resolve_dispute) → approved → paid
                                                                     ↘ refunded → refund_claimed
pending | submitted | rejected → propose_cancel (both parties) → refund_claimed
pending (only)                 → claim_timeout_refund (if refund window enabled) → refund_claimed
```

Each milestone moves through this independently of the others — one disputed milestone doesn't block payment on an already-approved one.

## What's new since v1

- **Real deliverable verification** — `submit_milestone` now takes a separate URL and description. If a URL is given, `review_milestone` has the AI leader fetch the live page (`gl.nondet.web.render`) and judge the actual content, not just the freelancer's own claim about it. If the fetch fails, it falls back to judging the description alone rather than hard-failing.
- **Platform fee** — an optional, capped (max 10%) basis-points fee, set by the Registry owner, locked in per-deal at funding time, and deducted only from an approved payout — never from refunds or cancellations.
- **Mutual cancellation** — `propose_cancel` lets either party vote to call off a milestone; once both have voted, funds return to the buyer immediately, no AI verdict needed.
- **Timed refund window** — a deal can optionally let the buyer reclaim a milestone's funds unilaterally if the freelancer never submits anything before a delay elapses.
- **Admin controls** — the Registry has an owner who can adjust the fee, treasury address, and pause new deal funding (in-flight deals are unaffected).
- **Debug transparency** — `get_last_raw_response` exposes the last unparsed AI output for a milestone review, for troubleshooting an unexpected verdict.

## Tech Stack

| Layer | Technologies |
| --- | --- |
| Server | Express 5 — static files, public config, and the Deal contract's source text. No wallet. |
| Client | Plain HTML/CSS/JS (ES modules), `genlayer-js` (CDN, version-pinned to match the ecosystem standard) |
| Network | GenLayer Bradbury testnet |
| Contracts | `contracts/registry.py`, `contracts/deal.py` |

## Getting Started

1. Deploy `contracts/registry.py` **once** via GenLayer Studio to Bradbury.
2. Put its address in `.env` as `REGISTRY_ADDRESS` (see `.env.example`).
3. `npm install && npm run dev`

Deal contracts need no separate deployment step from you — every buyer deploys their own deal from the New Deal page, using their own wallet.

## Testing

```
pip install -r tests/requirements.txt
# start GenLayer Studio locally first
pytest tests/test.py -v -s
```

Covers: unfunded deals, exact-amount funding validation, buyer-only funding, registry sync on funding, freelancer-only milestone submission, the full approve → claim → double-claim-rejected flow, dispute preconditions, and milestone independence within a multi-milestone deal.

---

© EscrowCourt — AI-arbitrated milestone escrow powered by GenLayer.
