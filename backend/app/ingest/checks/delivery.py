"""Delivery checks: did the right files arrive for this platform-week?

Adding a delivery check = write one `(context) -> CheckResult` function and add it to DELIVERY_CHECKS.
"""
import filecmp

from .types import CheckResult, DeliveryContext


def check_delivery_presence(context: DeliveryContext) -> CheckResult:
    if context.source_file is None:
        return CheckResult("delivery presence", "fail", {
            "message": f"No file received (expected {context.expected_filename})",
            "expected_filename": context.expected_filename,
        })
    return CheckResult("delivery presence", "pass", {"message": f"Received {context.source_file.name}"})


def check_duplicate_delivery(context: DeliveryContext) -> CheckResult:
    original_file, resend_file = context.original_file, context.resend_file
    if not (original_file and resend_file):
        return CheckResult("duplicate delivery", "pass", {"message": "One file received for this week"})
    identical = filecmp.cmp(original_file, resend_file, shallow=False)
    return CheckResult("duplicate delivery", "warn", {
        "message": f"Two files for this week: {resend_file.name} and {original_file.name} "
                   f"({'byte-identical' if identical else 'contents differ'}); only the resend was loaded",
        "identical": identical,
    })


DELIVERY_CHECKS = [check_delivery_presence, check_duplicate_delivery]
