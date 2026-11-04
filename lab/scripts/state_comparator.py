
def compare_state(expected, observed):
    # No usable evidence
    if not isinstance(observed, dict):
        return {
            "status": "insufficient_evidence",
            "differences": [],
        }

    # Check that expected fields exist
    missing = [
        key for key in expected
        if key not in observed
    ]

    if missing:
        return {
            "status": "insufficient_evidence",
            "differences": [],
            "missing_fields": missing,
        }

    # Compare expected and observed values
    differences = []

    for key, expected_value in expected.items():
        observed_value = observed[key]

        if expected_value != observed_value:
            differences.append({
                "field": key,
                "expected": expected_value,
                "observed": observed_value,
            })

    return {
        "status": "mismatch" if differences else "match",
        "differences": differences,
    }
