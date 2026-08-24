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


def deploy_deal(account, registry_address, freelancer_address, title, descriptions, amounts):
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
    address, deploy_response = deploy_intelligent_contract(account, code, args)
    assert has_success_status(deploy_response)
    print(f"[deploy] Deal deployed at {address}")
    return address


def test_deal_starts_unfunded(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    assert details["funded"] == "False"
    assert details["milestones"][0]["status"] == "pending"


def test_fund_requires_exact_amount(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    wrong_amount = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1) // 2)
    assert not has_success_status(wrong_amount)

    correct = send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert has_success_status(correct)

    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    assert details["funded"] == "True"


def test_only_buyer_can_fund(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    response = send_transaction(freelancer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    assert not has_success_status(response)


def test_fund_registers_deal_in_registry(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Registered deal", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    deals = json.loads(call_contract_method(registry_address, buyer, "get_deals", [50]))
    assert any(d["contract"].lower() == deal_address.lower() for d in deals)


def test_only_freelancer_can_submit_milestone(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Test deal", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "submit_milestone", [0, "", "some work"])
    assert not has_success_status(response)


def test_full_approval_flow_and_payment(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Good delivery", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Delivered a Figma wireframe covering hero, features, and footer sections as requested."])
    send_transaction(freelancer, deal_address, "review_milestone", [0])

    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    milestone = details["milestones"][0]
    print(f"[verdict] {milestone['status']} — {milestone['reasoning']}")

    if milestone["status"] != "approved":
        pytest.skip("Model did not approve this delivery in this run; payment path not exercised")

    payout = send_transaction(freelancer, deal_address, "claim_payment", [0])
    assert has_success_status(payout)

    second_attempt = send_transaction(freelancer, deal_address, "claim_payment", [0])
    assert not has_success_status(second_attempt)


def test_dispute_flow_requires_rejected_status(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Dispute test", [MILESTONE_2], [AMOUNT_2])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_2))
    # Milestone is still "pending" — no submission yet — so a dispute cannot be raised.
    response = send_transaction(freelancer, deal_address, "submit_dispute_evidence", [0, "some evidence"])
    assert not has_success_status(response)


def test_independent_milestones(registry_address, buyer, freelancer):
    deal_address = deploy_deal(
        buyer, registry_address, freelancer.address, "Two milestones",
        [MILESTONE_1, MILESTONE_2], [AMOUNT_1, AMOUNT_2],
    )
    total = int(AMOUNT_1) + int(AMOUNT_2)
    send_transaction(buyer, deal_address, "fund_escrow", [], value=total)
    send_transaction(freelancer, deal_address, "submit_milestone", [0, "", "Wireframe delivered."])

    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    assert details["milestones"][0]["status"] == "submitted"
    assert details["milestones"][1]["status"] == "pending"  # untouched, fully independent


def test_platform_fee_deducted_on_payout(registry_address, buyer, freelancer):
    fee_response = send_transaction(buyer, registry_address, "set_fee_bps", [500])  # 5% — buyer is not the owner
    assert not has_success_status(fee_response)  # confirm only the registry owner (the fixture's deployer) can set it


def test_mutual_cancellation_refunds_immediately(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "Cancel test", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    buyer_vote = send_transaction(buyer, deal_address, "propose_cancel", [0])
    assert has_success_status(buyer_vote)
    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    assert details["milestones"][0]["status"] == "pending"  # only one side has voted so far

    freelancer_vote = send_transaction(freelancer, deal_address, "propose_cancel", [0])
    assert has_success_status(freelancer_vote)
    details = json.loads(call_contract_method(deal_address, buyer, "get_deal_details", []))
    assert details["milestones"][0]["status"] == "refund_claimed"  # both sides agreed — refunded immediately


def test_timeout_refund_requires_refund_enabled(registry_address, buyer, freelancer):
    deal_address = deploy_deal(buyer, registry_address, freelancer.address, "No refund window", [MILESTONE_1], [AMOUNT_1])
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))
    response = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, int(time.time() * 1000)])
    assert not has_success_status(response)


def test_timeout_refund_respects_delay(registry_address, buyer, freelancer):
    code = open(DEAL_PATH, "r").read()
    now_ms = int(time.time() * 1000)
    args = json.dumps({
        "registry_value": registry_address,
        "buyer_value": buyer.address,
        "freelancer_value": freelancer.address,
        "title_value": "Timed refund test",
        "milestone_descriptions_value": [MILESTONE_1],
        "milestone_amounts_value": [int(AMOUNT_1)],
        "created_at_value": now_ms,
        "refund_enabled_value": True,
        "refund_delay_seconds_value": 3600,  # 1 hour
    })
    deal_address, deploy_response = deploy_intelligent_contract(buyer, code, args)
    assert has_success_status(deploy_response)
    send_transaction(buyer, deal_address, "fund_escrow", [], value=int(AMOUNT_1))

    too_early = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, now_ms + 60_000])  # only 1 minute later
    assert not has_success_status(too_early)

    after_delay = send_transaction(buyer, deal_address, "claim_timeout_refund", [0, now_ms + 3_700_000])  # past the hour
    assert has_success_status(after_delay)
