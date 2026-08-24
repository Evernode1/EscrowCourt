"""
EscrowCourt end-to-end contract test.

Runs against a local GenLayer Studio instance, following GenLayer's official
testing pattern: https://docs.genlayer.com/developers/decentralized-applications/testing

    pip install -r tests/requirements.txt
    # start GenLayer Studio locally first
    pytest tests/test.py -v -s
"""

import json
import time

import pytest
from tools.request import (
    create_new_account,
    deploy_intelligent_contract,
    send_transaction,
    call_contract_method,
)
from tools.response import has_success_status

REGISTRY_PATH = "contracts/registry.py"
DEAL_PATH = "contracts/deal.py"

MILESTONE_1 = "Deliver a homepage wireframe in Figma matching the brief."
MILESTONE_2 = "Implement the homepage in responsive HTML/CSS matching the approved wireframe."
AMOUNT_1 = "500000000000000000"   # 0.5 GEN
AMOUNT_2 = "1000000000000000000"  # 1.0 GEN


@pytest.fixture(scope="module")
def buyer():
    return create_new_account()


@pytest.fixture(scope="module")
def freelancer():
    return create_new_account()


@pytest.fixture(scope="module")
def registry_address(buyer):
    code = open(REGISTRY_PATH, "r").read()
    address, deploy_response = deploy_intelligent_contract(buyer, code, "{}")
    assert has_success_status(deploy_response)
    print(f"\n[deploy] Registry deployed at {address}")
    return address


def deploy_registry(account):
    """Deploy a fresh Registry so admin-mutating tests never contaminate
    the shared module-scoped registry_address used by other tests."""
    code = open(REGISTRY_PATH, "r").read()
    address, deploy_response = deploy_intelligent_contract(account, code, "{}")
    assert has_success_status(deploy_response)
    return address


def deploy_deal(account, registry_address, freelancer_address, title, descriptions, amounts,
                refund_enabled=False, refund_delay_seconds=0, created_at=None):
    code = open(DEAL_PATH, "r").read()
    args = json.dumps({
        "registry_value": registry_address,
        "buyer_value": account.address,
        "freelancer_value": freelancer_address,
        "title_value": title,
        "milestone_descriptions_value": descriptions,
        "milestone_amounts_value": [int(a) for a in amounts],
        "created_at_value": created_at if created_at is not None else int(time.time() * 1000),
        "refund_enabled_value": refund_enabled,
        "refund_delay_seconds_value": refund_delay_seconds,
    })
    address, deploy_response = deploy_intelligent_contract(account, code, args)
    assert has_success_status(deploy_response)
    print(f"[deploy] Deal deployed at {address}")
    return address


def deploy_deal_raw(account, registry_address, freelancer_address, title, descriptions, amounts):
    """Like deploy_deal, but returns the raw (address, deploy_response) pair
    instead of asserting success — for tests that expect deployment to fail."""
    code = open(DEAL_PATH, "r").read()
    args = json.dumps({
        "registry_value": registry_address,
        "buyer_value": account.address,
        "freelancer_value": freelancer_address,
        "title_value": title,
        "milestone_descriptions_value": descriptions,
        "milestone_amounts_value": [int(a) for a in amounts],
        "created_at_value": int(time.time() * 1000),
        "refund_enabled_value": False,
        "refund_delay_seconds_value": 0,
    })
    return deploy_intelligent_contract(account, code, args)


def get_details(deal_address, caller):
    return json.loads(call_contract_method(deal_address, caller, "get_deal_details", []))


def unwrap(value):
    """Contract `str`-returning view methods may come back as a plain string
    or as a JSON-quoted string depending on the RPC layer; normalize either."""
    if isinstance(value, str) and value.strip().startswith('"') and value.strip().endswith('"'):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# Deployment / constructor validation
# ---------------------------------------------------------------------------

def test_deal_starts_unfunded(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    details = get_details(deal_address, buyer)
    assert details["funded"] == "False"
    assert details["milestones"][0]["status"] == "pending"


def test_deploy_rejects_zero_milestones(registry_address, buyer, freelancer):
    _, deploy_response = deploy_deal_raw(buyer, registry_address, freelancer.address, "No milestones", [], [])
    assert not has_success_status(deploy_response)


def test_deploy_rejects_mismatched_descriptions_and_amounts(registry_address, buyer, freelancer):
    _, deploy_response = deploy_deal_raw(
        buyer, registry_address, freelancer.address, "Mismatched",
        [MILESTONE_1, MILESTONE_2], [AMOUNT_1],  # 2 descriptions, 1 amount
    )
    assert not has_success_status(deploy_response)


# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------

def test_fund_requires_exact_amount(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    wrong_amount = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1) // 2)
    assert not has_success_status(wrong_amount)

    correct = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert has_success_status(correct)

    details = get_details(deal_address, buyer)
    assert details["funded"] == "True"


def test_only_buyer_can_fund(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    response = send_transaction(freelancer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert not has_success_status(response)


def test_cannot_fund_twice(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Double fund", [MILESTONE_1], [AMOUNT_1])
    first = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert has_success_status(first)

    second = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert not has_success_status(second)


def test_fund_registers_deal_in_registry(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Registered deal", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    deals = json.loads(call_contract_method(registry_address, buyer, "get_deals", [50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in deals)


def test_paused_registry_blocks_new_funding(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    deal_address = deploy_deal(buyer, fresh_registry, freelancer.address, "Paused test", [MILESTONE_1], [AMOUNT_1])

    pause_response = send_transaction(buyer, fresh_registry, "set_paused", [True])
    assert has_success_status(pause_response)

    funding_attempt = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert not has_success_status(funding_attempt)

    unpause_response = send_transaction(buyer, fresh_registry, "set_paused", [False])
    assert has_success_status(unpause_response)
    funding_after_unpause = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert has_success_status(funding_after_unpause)


def test_fee_bps_locked_in_at_funding_time(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    set_fee = send_transaction(buyer, fresh_registry, "set_fee_bps", [250])  # 2.5%
    assert has_success_status(set_fee)

    deal_address = deploy_deal(buyer, fresh_registry, freelancer.address, "Fee lock test", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    # Changing the fee after funding must not retroactively affect this deal.
    send_transaction(buyer, fresh_registry, "set_fee_bps", [900])

    details = get_details(deal_address, buyer)
    assert details["fee_bps_at_funding"] == "250"


# ---------------------------------------------------------------------------
# Registry admin controls
# ---------------------------------------------------------------------------

def test_only_owner_can_set_fee_bps(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)  # buyer is the deployer, i.e. the owner
    non_owner_attempt = send_transaction(freelancer, fresh_registry, "set_fee_bps", [500])
    assert not has_success_status(non_owner_attempt)

    owner_attempt = send_transaction(buyer, fresh_registry, "set_fee_bps", [500])
    assert has_success_status(owner_attempt)
    fee = unwrap(call_contract_method(fresh_registry, buyer, "get_fee_bps", []))
    assert fee == "500"


def test_fee_bps_cannot_exceed_ten_percent_cap(buyer):
    fresh_registry = deploy_registry(buyer)
    over_cap = send_transaction(buyer, fresh_registry, "set_fee_bps", [1001])
    assert not has_success_status(over_cap)

    at_cap = send_transaction(buyer, fresh_registry, "set_fee_bps", [1000])
    assert has_success_status(at_cap)


def test_only_owner_can_set_treasury(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    non_owner_attempt = send_transaction(freelancer, fresh_registry, "set_treasury", [freelancer.address])
    assert not has_success_status(non_owner_attempt)

    owner_attempt = send_transaction(buyer, fresh_registry, "set_treasury", [freelancer.address])
    assert has_success_status(owner_attempt)
    treasury = unwrap(call_contract_method(fresh_registry, buyer, "get_treasury", []))
    assert freelancer.address.lower() in treasury.lower()


def test_only_owner_can_set_paused(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    non_owner_attempt = send_transaction(freelancer, fresh_registry, "set_paused", [True])
    assert not has_success_status(non_owner_attempt)


def test_only_owner_can_transfer_ownership(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    non_owner_attempt = send_transaction(freelancer, fresh_registry, "transfer_ownership", [freelancer.address])
    assert not has_success_status(non_owner_attempt)

    owner_attempt = send_transaction(buyer, fresh_registry, "transfer_ownership", [freelancer.address])
    assert has_success_status(owner_attempt)

    new_owner = unwrap(call_contract_method(fresh_registry, buyer, "get_owner", []))
    assert freelancer.address.lower() in new_owner.lower()

    # Old owner has lost admin rights; new owner has gained them.
    old_owner_attempt = send_transaction(buyer, fresh_registry, "set_fee_bps", [100])
    assert not has_success_status(old_owner_attempt)
    new_owner_attempt = send_transaction(freelancer, fresh_registry, "set_fee_bps", [100])
    assert has_success_status(new_owner_attempt)


def test_registry_query_methods(buyer, freelancer):
    fresh_registry = deploy_registry(buyer)
    deal_address = deploy_deal(buyer, fresh_registry, freelancer.address, "Queryable deal", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    count = unwrap(call_contract_method(fresh_registry, buyer, "get_deal_count", []))
    assert int(count) >= 1

    active = json.loads(call_contract_method(fresh_registry, buyer, "get_deals_by_status", ["active", 50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in active)

    for_buyer = json.loads(call_contract_method(fresh_registry, buyer, "get_deals_for_address", [buyer.address, 50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in for_buyer)

    for_freelancer = json.loads(call_contract_method(fresh_registry, buyer, "get_deals_for_address", [freelancer.address, 50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in for_freelancer)


# ---------------------------------------------------------------------------
# Milestone submission
# ---------------------------------------------------------------------------

def test_only_freelancer_can_submit_milestone(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "submit_milestone", [0, "", "some work"])
    assert not has_success_status(response)


def test_cannot_submit_before_funding(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Unfunded submit", [MILESTONE_1], [AMOUNT_1])
    response = send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "work"])
    assert not has_success_status(response)


def test_submit_requires_url_or_description(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Empty submit", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "   "])
    assert not has_success_status(response)


def test_cannot_resubmit_while_already_submitted(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No resubmit", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    first = send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "First submission"])
    assert has_success_status(first)

    second = send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Second submission"])
    assert not has_success_status(second)


def test_submit_milestone_rejects_invalid_index(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Bad index", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(freelancer, deal_address, "submit_milestone", [5, "", "work"])
    assert not has_success_status(response)


def test_independent_milestones(registry_address, buyer, freelancer):
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Two milestones",
        [MILESTONE_1, MILESTONE_2], [AMOUNT_1, AMOUNT_2],
    )
    total = int(AMOUNT_1) + int(AMOUNT_2)
    send_transaction(buyer, deal_address, "fund_escrow", [], value=total)
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Wireframe delivered."])

    details = get_details(deal_address, buyer)
    assert details["milestones"][0]["status"] == "submitted"
    assert details["milestones"][1]["status"] == "pending"  # untouched, fully independent


# ---------------------------------------------------------------------------
# Review / approval / payment
# ---------------------------------------------------------------------------

def test_review_requires_submitted_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Premature review", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(freelancer, deal_address, "review_milestone", [0])
    assert not has_success_status(response)


def test_full_approval_flow_and_payment(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Good delivery", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Delivered a Figma wireframe covering hero, features, and footer sections as requested."])
    send_transaction(freelancer, deal_address, "review_milestone", [0])

    details = get_details(deal_address, buyer)
    milestone = details["milestones"][0]
    print(f"[verdict] {milestone['status']} — {milestone['reasoning']}")

    # get_last_raw_response should be populated regardless of verdict.
    raw = call_contract_method(deal_address, buyer, "get_last_raw_response", [0])
    assert raw is not None and len(raw) > 0

    if milestone["status"] != "approved":
        pytest.skip("Model did not approve this delivery in this run; payment path not exercised")

    payout = send_transaction(freelancer, deal_address, "claim_payment", [0])
    assert has_success_status(payout)

    second_attempt = send_transaction(freelancer, deal_address, "claim_payment", [0])
    assert not has_success_status(second_attempt)


def test_claim_payment_requires_approved_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No payout yet", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(freelancer, deal_address, "claim_payment", [0])
    assert not has_success_status(response)


def test_only_freelancer_can_claim_payment(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Wrong claimer", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Delivered a Figma wireframe covering hero, features, and footer sections as requested."])
    send_transaction(freelancer, deal_address, "review_milestone", [0])

    details = get_details(deal_address, buyer)
    if details["milestones"][0]["status"] != "approved":
        pytest.skip("Model did not approve this delivery in this run; claimer-guard not exercised")

    response = send_transaction(buyer, deal_address, "claim_payment", [0])
    assert not has_success_status(response)


# ---------------------------------------------------------------------------
# Disputes and refunds
# ---------------------------------------------------------------------------

def test_dispute_evidence_requires_rejected_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Dispute test", [MILESTONE_2], [AMOUNT_2])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_2))
    # Milestone is still "pending" — no submission yet — so a dispute cannot be raised.
    response = send_transaction(freelancer, deal_address, "submit_dispute_evidence", [0, "some evidence"])
    assert not has_success_status(response)


def test_resolve_dispute_requires_rejected_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No dispute yet", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "resolve_dispute", [0])
    assert not has_success_status(response)


def test_claim_refund_requires_refunded_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No refund yet", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "claim_refund", [0])
    assert not has_success_status(response)


def test_full_dispute_flow(registry_address, buyer, freelancer):
    """
    Submit a deliberately weak, unrelated deliverable so the AI review is
    likely to reject it, then walk the rejected milestone through the
    dispute path to a final binding verdict. The verdict itself is
    nondeterministic (AI-decided), so this test only skips the parts it
    genuinely cannot control, not the workflow's success/failure contracts.
    """
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Disputed delivery",
        ["Build a fully functional payment gateway integration with Stripe, including webhooks and refund handling."],
        [AMOUNT_2],
    )
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_2))
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "I drew a cat."])
    send_transaction(freelancer, deal_address, "review_milestone", [0])

    details = get_details(deal_address, buyer)
    status = details["milestones"][0]["status"]
    print(f"[verdict] initial review status: {status}")

    if status != "rejected":
        pytest.skip("Model did not reject this mismatched delivery in this run; dispute path not exercised")

    buyer_evidence = send_transaction(buyer, deal_address, "submit_dispute_evidence", [0, "This clearly does not meet the milestone requirement."])
    assert has_success_status(buyer_evidence)
    freelancer_evidence = send_transaction(freelancer, deal_address, "submit_dispute_evidence", [0, "I believe the drawing satisfies the creative intent of the brief."])
    assert has_success_status(freelancer_evidence)

    resolution = send_transaction(buyer, deal_address, "resolve_dispute", [0])
    assert has_success_status(resolution)

    details = get_details(deal_address, buyer)
    final_status = details["milestones"][0]["status"]
    print(f"[verdict] final dispute status: {final_status}")
    assert final_status in ("approved", "refunded")

    if final_status == "refunded":
        refund = send_transaction(buyer, deal_address, "claim_refund", [0])
        assert has_success_status(refund)
        details = get_details(deal_address, buyer)
        assert details["milestones"][0]["status"] == "refund_claimed"

        second_refund = send_transaction(buyer, deal_address, "claim_refund", [0])
        assert not has_success_status(second_refund)
    else:
        payout = send_transaction(freelancer, deal_address, "claim_payment", [0])
        assert has_success_status(payout)


# ---------------------------------------------------------------------------
# Mutual cancellation
# ---------------------------------------------------------------------------

def test_mutual_cancellation_refunds_immediately(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Cancel test", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    buyer_vote = send_transaction(buyer, deal_address, "propose_cancel", [0])
    assert has_success_status(buyer_vote)
    details = get_details(deal_address, buyer)
    assert details["milestones"][0]["status"] == "pending"  # only one side has voted so far

    freelancer_vote = send_transaction(freelancer, deal_address, "propose_cancel", [0])
    assert has_success_status(freelancer_vote)
    details = get_details(deal_address, buyer)
    assert details["milestones"][0]["status"] == "refund_claimed"  # both sides agreed — refunded immediately


def test_deal_marked_completed_in_registry_after_resolution(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Single-milestone completion", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    send_transaction(buyer, deal_address, "propose_cancel", [0])
    send_transaction(freelancer, deal_address, "propose_cancel", [0])  # both vote -> only milestone resolves -> deal completes

    completed = json.loads(call_contract_method(registry_address, buyer, "get_deals_by_status", ["completed", 50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in completed)


# ---------------------------------------------------------------------------
# Timed refund window
# ---------------------------------------------------------------------------

def test_timeout_refund_requires_refund_enabled(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No refund window", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, int(time.time() * 1000)])
    assert not has_success_status(response)


def test_only_buyer_can_claim_timeout_refund(registry_address, buyer, freelancer):
    now_ms = int(time.time() * 1000)
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Wrong claimer timeout", [MILESTONE_1], [AMOUNT_1],
        refund_enabled=True, refund_delay_seconds=1, created_at=now_ms,
    )
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(freelancer, deal_address, "claim_timeout_refund", [0, now_ms + 5_000])
    assert not has_success_status(response)


def test_timeout_refund_respects_delay(registry_address, buyer, freelancer):
    now_ms = int(time.time() * 1000)
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Timed refund test", [MILESTONE_1], [AMOUNT_1],
        refund_enabled=True, refund_delay_seconds=3600, created_at=now_ms,  # 1 hour
    )
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    too_early = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, now_ms + 60_000])  # only 1 minute later
    assert not has_success_status(too_early)

    after_delay = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, now_ms + 3_700_000])  # past the hour
    assert has_success_status(after_delay)

    details = get_details(deal_address, buyer)
    assert details["milestones"][0]["status"] == "refund_claimed"


def test_timeout_refund_only_applies_before_submission(registry_address, buyer, freelancer):
    now_ms = int(time.time() * 1000)
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Already submitted", [MILESTONE_1], [AMOUNT_1],
        refund_enabled=True, refund_delay_seconds=1, created_at=now_ms,
    )
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Work submitted before timeout."])

    response = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, now_ms + 5_000])
    assert not has_success_status(response)
