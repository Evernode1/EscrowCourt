# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

MILESTONE_STATUSES = ("pending", "submitted", "approved", "rejected", "paid", "refunded")


class Deal(gl.Contract):
    registry: Address
    buyer: Address
    freelancer: Address
    title: str
    created_at: str
    funded: bool
    fee_bps_at_funding: u256

    refund_enabled: bool
    refund_delay_seconds: u256

    milestone_descriptions: DynArray[str]
    milestone_amounts: DynArray[u256]
    milestone_status: DynArray[str]
    milestone_deliverable_url: DynArray[str]
    milestone_deliverable_description: DynArray[str]
    milestone_reasoning: DynArray[str]
    milestone_last_raw_response: DynArray[str]
    milestone_buyer_evidence: DynArray[str]
    milestone_freelancer_evidence: DynArray[str]
    milestone_buyer_cancel_vote: DynArray[bool]
    milestone_freelancer_cancel_vote: DynArray[bool]

    def __init__(
        self,
        registry_value: str,
        buyer_value: str,
        freelancer_value: str,
        title_value: str,
        milestone_descriptions_value: list[str],
        milestone_amounts_value: list[int],
        created_at_value: int,
        refund_enabled_value: bool,
        refund_delay_seconds_value: int,
    ):
        if len(milestone_descriptions_value) == 0:
            raise Exception("A deal must have at least one milestone")
        if len(milestone_descriptions_value) != len(milestone_amounts_value):
            raise Exception("Milestone descriptions and amounts must match in length")

        self.registry = Address(registry_value)
        self.buyer = Address(buyer_value)
        self.freelancer = Address(freelancer_value)
        self.title = title_value
        self.created_at = str(created_at_value)
        self.funded = False
        self.fee_bps_at_funding = u256(0)
        self.refund_enabled = refund_enabled_value
        self.refund_delay_seconds = u256(max(0, refund_delay_seconds_value))

        for i in range(len(milestone_descriptions_value)):
            self.milestone_descriptions.append(milestone_descriptions_value[i])
            self.milestone_amounts.append(u256(milestone_amounts_value[i]))
            self.milestone_status.append("pending")
            self.milestone_deliverable_url.append("")
            self.milestone_deliverable_description.append("")
            self.milestone_reasoning.append("")
            self.milestone_last_raw_response.append("")
            self.milestone_buyer_evidence.append("")
            self.milestone_freelancer_evidence.append("")
            self.milestone_buyer_cancel_vote.append(False)
            self.milestone_freelancer_cancel_vote.append(False)

    def _total_amount(self) -> u256:
        total = u256(0)
        for amount in self.milestone_amounts:
            total = u256(total + amount)
        return total

    @gl.public.write.payable
    def fund_escrow(self):
        if gl.message.sender_address.as_hex.lower() != self.buyer.as_hex.lower():
            raise Exception("Only the buyer can fund this deal")
        if self.funded:
            raise Exception("Deal is already funded")
        if gl.message.value != self._total_amount():
            raise Exception("Sent amount must exactly match the sum of all milestone amounts")

        registry_contract = gl.get_contract_at(self.registry)
        if registry_contract.view().get_paused():
            raise Exception("EscrowCourt is currently paused for new deals")

        # Lock in the fee rate at funding time, so a later platform fee change
        # never retroactively affects a deal already in flight.
        self.fee_bps_at_funding = u256(int(registry_contract.view().get_fee_bps()))
        self.funded = True
        registry_contract.emit().register_deal(
            self.buyer.as_hex,
            self.freelancer.as_hex,
            self.title,
            int(self._total_amount()),
            int(self.created_at),
        )

    @gl.public.write
    def submit_milestone(self, index: int, deliverable_url: str, deliverable_description: str):
        if not self.funded:
            raise Exception("Deal is not funded yet")
        if gl.message.sender_address.as_hex.lower() != self.freelancer.as_hex.lower():
            raise Exception("Only the freelancer can submit milestone work")
        self._check_index(index)
        status = self.milestone_status[index]
        if status not in ("pending", "rejected"):
            raise Exception(f"Milestone cannot be submitted from status '{status}'")
        if not deliverable_url.strip() and not deliverable_description.strip():
            raise Exception("Provide a deliverable URL, a description, or both")
        self.milestone_deliverable_url[index] = deliverable_url.strip()
        self.milestone_deliverable_description[index] = deliverable_description.strip()
        self.milestone_status[index] = "submitted"
        self.milestone_buyer_cancel_vote[index] = False
        self.milestone_freelancer_cancel_vote[index] = False

    @gl.public.write
    def review_milestone(self, index: int):
        self._check_index(index)
        if self.milestone_status[index] != "submitted":
            raise Exception("Milestone is not awaiting review")

        description = self.milestone_descriptions[index]
        url = self.milestone_deliverable_url[index]
        deliverable_description = self.milestone_deliverable_description[index]

        def leader_fn():
            page_content = ""
            fetch_note = "No deliverable URL was submitted — judge from the description alone."
            if url:
                try:
                    page_content = gl.nondet.web.render(url, mode="text")
                    fetch_note = "The live page content below was fetched directly from the submitted URL — judge the ACTUAL content, not just the freelancer's description of it."
                except Exception as fetch_error:
                    fetch_note = f"The submitted URL could not be fetched ({fetch_error}). Judge from the description alone, and note the unverifiable link in your reasoning."

            prompt = f"""You are an impartial escrow reviewer on a decentralized freelance platform. Multiple independent validators will review this same milestone and must reach consensus.

MILESTONE REQUIREMENT (agreed upon by both parties beforehand):
\"\"\"{description}\"\"\"

FREELANCER'S OWN DESCRIPTION OF THE DELIVERED WORK:
\"\"\"{deliverable_description or "(no description given)"}\"\"\"

DELIVERABLE URL: {url or "(none provided)"}
{fetch_note}

LIVE FETCHED PAGE CONTENT (if available):
\"\"\"{page_content[:4000] if page_content else "(not available)"}\"\"\"

Decide whether the actual deliverable reasonably satisfies the milestone requirement. Prioritize the live fetched content over the freelancer's own description when both are available — the freelancer's description alone is not sufficient proof. Be fair to both sides: don't reject over trivial gaps, but don't approve work that clearly misses the requirement's substance or that you could not verify at all.

Respond ONLY with a JSON object in this exact format:
{{
    "verdict": "approved" | "rejected",
    "reasoning": str (one to two concise sentences explaining the decision, at least 10 words)
}}
It is mandatory that you respond only using the JSON format above, nothing else.
Don't include any other words, characters, or markdown formatting.
Your output must be perfectly parsable by a JSON parser without errors.
"""
            raw = gl.nondet.exec_prompt(prompt)
            parsed = json.loads(_extract_json_from_string(raw))
            parsed["verdict"] = str(parsed["verdict"]).strip().lower()
            if parsed["verdict"] not in ("approved", "rejected"):
                parsed["verdict"] = "rejected"
            parsed["reasoning"] = str(parsed["reasoning"])
            parsed["_raw"] = raw
            return parsed

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            leader_data = leader_result.calldata
            validator_data = leader_fn()
            return leader_data["verdict"] == validator_data["verdict"]

        result = gl.vm.run_nondet(leader_fn, validator_fn)
        self.milestone_status[index] = result["verdict"]
        self.milestone_reasoning[index] = result["reasoning"]
        self.milestone_last_raw_response[index] = str(result.get("_raw", ""))[:2000]

    @gl.public.write
    def submit_dispute_evidence(self, index: int, evidence: str):
        self._check_index(index)
        if self.milestone_status[index] != "rejected":
            raise Exception("Disputes can only be raised on a rejected milestone")
        sender = gl.message.sender_address.as_hex.lower()
        if sender == self.buyer.as_hex.lower():
            self.milestone_buyer_evidence[index] = evidence.strip()
        elif sender == self.freelancer.as_hex.lower():
            self.milestone_freelancer_evidence[index] = evidence.strip()
        else:
            raise Exception("Only the buyer or freelancer can submit evidence")

    @gl.public.write
    def resolve_dispute(self, index: int):
        self._check_index(index)
        if self.milestone_status[index] != "rejected":
            raise Exception("Only a rejected milestone can be escalated to a binding dispute")
        buyer_evidence = self.milestone_buyer_evidence[index] or "(the buyer did not submit evidence)"
        freelancer_evidence = self.milestone_freelancer_evidence[index] or "(the freelancer did not submit evidence)"
        description = self.milestone_descriptions[index]
        deliverable = self.milestone_deliverable_description[index]
        prior_reasoning = self.milestone_reasoning[index]

        def leader_fn():
            prompt = f"""You are an impartial arbitrator making a FINAL, BINDING decision in an escrow dispute. Multiple independent validators will review this same dispute and must reach consensus.

MILESTONE REQUIREMENT:
\"\"\"{description}\"\"\"

FREELANCER'S DELIVERABLE DESCRIPTION:
\"\"\"{deliverable}\"\"\"

AN EARLIER AUTOMATED REVIEW REJECTED THIS DELIVERABLE, REASONING:
\"\"\"{prior_reasoning}\"\"\"

BUYER'S DISPUTE EVIDENCE / STATEMENT:
\"\"\"{buyer_evidence}\"\"\"

FREELANCER'S DISPUTE EVIDENCE / STATEMENT:
\"\"\"{freelancer_evidence}\"\"\"

Weigh both sides' evidence fairly and independently of the earlier automated rejection — you may overturn it if the evidence justifies that. This decision is final: the milestone payment will be released to the freelancer if you rule "approved", or refunded to the buyer if you rule "refunded".

Respond ONLY with a JSON object in this exact format:
{{
    "verdict": "approved" | "refunded",
    "reasoning": str (two to three concise sentences explaining the final decision)
}}
It is mandatory that you respond only using the JSON format above, nothing else.
Don't include any other words, characters, or markdown formatting.
Your output must be perfectly parsable by a JSON parser without errors.
"""
            raw = gl.nondet.exec_prompt(prompt)
            parsed = json.loads(_extract_json_from_string(raw))
            parsed["verdict"] = str(parsed["verdict"]).strip().lower()
            if parsed["verdict"] not in ("approved", "refunded"):
                parsed["verdict"] = "refunded"
            parsed["reasoning"] = str(parsed["reasoning"])
            return parsed

        def validator_fn(leader_result: gl.vm.Result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            leader_data = leader_result.calldata
            validator_data = leader_fn()
            return leader_data["verdict"] == validator_data["verdict"]

        result = gl.vm.run_nondet(leader_fn, validator_fn)
        self.milestone_status[index] = result["verdict"]
        self.milestone_reasoning[index] = result["reasoning"]
        self._maybe_close_deal()

    @gl.public.write
    def propose_cancel(self, index: int):
        """
        Mutual-consent cancellation: once both buyer and freelancer have
        called this for the same milestone, the full amount refunds to the
        buyer immediately — no verdict, no fee, no dispute needed.
        """
        self._check_index(index)
        status = self.milestone_status[index]
        if status not in ("pending", "submitted", "rejected"):
            raise Exception(f"Milestone in status '{status}' cannot be cancelled")

        sender = gl.message.sender_address.as_hex.lower()
        if sender == self.buyer.as_hex.lower():
            self.milestone_buyer_cancel_vote[index] = True
        elif sender == self.freelancer.as_hex.lower():
            self.milestone_freelancer_cancel_vote[index] = True
        else:
            raise Exception("Only the buyer or freelancer can propose cancellation")

        if self.milestone_buyer_cancel_vote[index] and self.milestone_freelancer_cancel_vote[index]:
            amount = self.milestone_amounts[index]
            self.milestone_status[index] = "refund_claimed"
            self.milestone_reasoning[index] = "Cancelled by mutual agreement between buyer and freelancer."
            gl.emit_transfer(self.buyer, amount)
            self._maybe_close_deal()

    @gl.public.write
    def claim_timeout_refund(self, index: int, checked_at: int):
        """
        If the deal was created with a refund window and the freelancer
        never submitted anything before it elapsed, the buyer can reclaim
        that milestone's funds unilaterally. `checked_at` is the caller's
        current time in epoch milliseconds, matching `created_at`.
        """
        self._check_index(index)
        if not self.refund_enabled:
            raise Exception("Timed refunds are not enabled on this deal")
        if gl.message.sender_address.as_hex.lower() != self.buyer.as_hex.lower():
            raise Exception("Only the buyer can claim a timeout refund")
        if self.milestone_status[index] != "pending":
            raise Exception("Timeout refund only applies before the freelancer has submitted anything")
        elapsed_seconds = (checked_at - int(self.created_at)) / 1000
        if elapsed_seconds < int(self.refund_delay_seconds):
            raise Exception("The refund delay has not elapsed yet")
        amount = self.milestone_amounts[index]
        self.milestone_status[index] = "refund_claimed"
        self.milestone_reasoning[index] = "Refunded to buyer after the timeout window elapsed with no submission."
        gl.emit_transfer(self.buyer, amount)
        self._maybe_close_deal()

    @gl.public.write
    def claim_payment(self, index: int):
        self._check_index(index)
        if gl.message.sender_address.as_hex.lower() != self.freelancer.as_hex.lower():
            raise Exception("Only the freelancer can claim a milestone payment")
        if self.milestone_status[index] != "approved":
            raise Exception("Milestone is not in an approved, claimable state")
        amount = self.milestone_amounts[index]
        self.milestone_status[index] = "paid"

        fee = u256((int(amount) * int(self.fee_bps_at_funding)) // 10000)
        payout = u256(int(amount) - int(fee))
        gl.emit_transfer(self.freelancer, payout)
        if fee > 0:
            registry_contract = gl.get_contract_at(self.registry)
            treasury = Address(registry_contract.view().get_treasury())
            gl.emit_transfer(treasury, fee)

        self._maybe_close_deal()

    @gl.public.write
    def claim_refund(self, index: int):
        self._check_index(index)
        if gl.message.sender_address.as_hex.lower() != self.buyer.as_hex.lower():
            raise Exception("Only the buyer can claim a milestone refund")
        if self.milestone_status[index] != "refunded":
            raise Exception("Milestone is not in a refunded, claimable state")
        amount = self.milestone_amounts[index]
        self.milestone_status[index] = "refund_claimed"
        gl.emit_transfer(self.buyer, amount)
        self._maybe_close_deal()

    def _maybe_close_deal(self):
        for status in self.milestone_status:
            if status not in ("paid", "refund_claimed"):
                return
        registry_contract = gl.get_contract_at(self.registry)
        registry_contract.emit().update_status("completed")

    def _check_index(self, index: int):
        if index < 0 or index >= len(self.milestone_descriptions):
            raise Exception("Invalid milestone index")

    @gl.public.view
    def get_last_raw_response(self, index: int) -> str:
        self._check_index(index)
        return self.milestone_last_raw_response[index]

    @gl.public.view
    def get_deal_details(self) -> str:
        milestones = []
        for i in range(len(self.milestone_descriptions)):
            milestones.append({
                "index": i,
                "description": self.milestone_descriptions[i],
                "amount": str(self.milestone_amounts[i]),
                "status": self.milestone_status[i],
                "deliverable_url": self.milestone_deliverable_url[i],
                "deliverable_description": self.milestone_deliverable_description[i],
                "reasoning": self.milestone_reasoning[i],
                "buyer_evidence": self.milestone_buyer_evidence[i],
                "freelancer_evidence": self.milestone_freelancer_evidence[i],
                "buyer_cancel_vote": str(self.milestone_buyer_cancel_vote[i]),
                "freelancer_cancel_vote": str(self.milestone_freelancer_cancel_vote[i]),
            })
        return json.dumps({
            "registry": self.registry.as_hex,
            "buyer": self.buyer.as_hex,
            "freelancer": self.freelancer.as_hex,
            "title": self.title,
            "created_at": self.created_at,
            "funded": str(self.funded),
            "fee_bps_at_funding": str(self.fee_bps_at_funding),
            "refund_enabled": str(self.refund_enabled),
            "refund_delay_seconds": str(self.refund_delay_seconds),
            "total_amount": str(self._total_amount()),
            "milestones": milestones,
        })


def _extract_json_from_string(s: str) -> str:
    """Extract a JSON object substring from a raw LLM response string."""
    start_index = s.find("{")
    end_index = s.rfind("}")
    if start_index != -1 and end_index != -1 and start_index < end_index:
        return s[start_index : end_index + 1]
    else:
        return ""
