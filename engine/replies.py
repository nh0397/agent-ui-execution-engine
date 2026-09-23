"""User-facing answers from verified results. No model calls or persisted raw outputs."""
import re
from decimal import Decimal


def result_reply(result, contract, mode="replay"):
    if result.status == "business_outcome":
        return {
            "Customer not found": "I couldn't find that customer. Please check the customer ID.",
            "Account not found": "I couldn't find that account. Please check the account ID.",
            "Card not found": "I couldn't find that card. Please check the card ID.",
            "Card already in requested state": "The card is already in the requested state. No change was needed.",
            "Invalid address": "The bank didn't accept that address. Please check the address details.",
            "Record changed during review": "The record changed while it was being reviewed. Please check the latest details before trying again.",
        }.get(result.code, "The bank didn't complete the requested change. Check the run details for its response.")
    if result.status != "success":
        if result.code == "Permission denied":
            return "I couldn't complete this because the bank denied access."
        return "I couldn't verify that the task finished. Check the run details before trying again; a change may already have been saved."
    if mode == "recording":
        return "Done — I captured the steps. Review and publish the workflow before using it again."

    # Recorded workflows may rename output keys. Prefer their declared field labels.
    def output(label, *keys):
        for action in getattr(contract, "steps", []):
            if action.kind == "read" and action.target.name == label:
                value = result.outputs.get(action.output_key)
                if value and value != "[REDACTED]":
                    return value
        for key in keys:
            value = result.outputs.get(key)
            if value and value != "[REDACTED]":
                return value
        return None

    heading = contract.success.name
    if heading == "Account balance verified":
        balance = output("Account balance", "balance", "account_balance")
        account = output("Verified account ID", "account_id")
        if balance and re.fullmatch(r"-?\d{1,16}(?:\.\d{1,2})?", balance) and account:
            return f"The balance of account {account} is ${Decimal(balance):,.2f} USD. This is the ledger balance shown when I checked."
        return "I opened the account, but the workflow didn't return a verified balance and account ID for me to show you."
    if heading == "Address updated":
        customer = output("Saved customer ID", "customer_id")
        message = f"Done — I updated the mailing address for customer {customer}." if customer else "Done — I updated the mailing address."
    elif heading in {"Card frozen", "Card unfrozen"}:
        card = output("Saved card ID", "card_id")
        action = "frozen" if heading == "Card frozen" else "unfrozen"
        message = f"Done — I've {action} debit card {card}." if card else f"Done — I've {action} the debit card."
    else:
        details = [f"{key.replace('_', ' ')}: {value}" for key, value in result.outputs.items() if value != "[REDACTED]"]
        message = "Done — I completed the task." + ("\n" + "\n".join(details) if details else "")
    if mode == "discovery":
        message += " I've also saved the workflow so you can use it again."
    return message
