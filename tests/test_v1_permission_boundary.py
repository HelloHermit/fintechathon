"""Independent V1 checks based only on permission specifications and PUBLIC_API.

The author has not read business Python source, prior tests, or reproduction
scripts. SQLite access uses documented tables only to establish and verify
fixtures. Run this file directly with the bundled Python and -B; it creates
only temporary databases and the dedicated acceptance evidence file.
"""

import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(hours=8)))
QUERY_PARAMETERS = {"start_date": "2026-10-01", "end_date": "2026-10-11"}
PROTECTED_RESULT_FIELDS = ("subscriptions", "future_expected_cents")


class V1PermissionBoundaryTests(unittest.TestCase):
    """Check historical facts separately from current subscription arrangements."""

    @classmethod
    def setUpClass(cls):
        if str(REPOSITORY_ROOT) not in sys.path:
            sys.path.insert(0, str(REPOSITORY_ROOT))
        # Import the documented public interface; do not inspect its source.
        from src.bank import BankService

        cls.service_class = BankService

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="fintechathon-v1-independent-"
        )
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture_directory = Path(self.temporary_directory.name)

    def _open_service(self, database_path):
        service = self.service_class(
            database_path, user_id="alice", clock=lambda: FIXED_TIME
        )
        self.addCleanup(service.close)
        return service

    @staticmethod
    def _historical_snapshot(database_path):
        """Read all documented account and transaction facts without audit data."""
        with closing(sqlite3.connect(database_path)) as connection:
            accounts = connection.execute(
                "SELECT account_id, user_id, balance_cents FROM accounts "
                "ORDER BY account_id"
            ).fetchall()
            transactions = connection.execute(
                "SELECT transaction_id, user_id, account_id, amount_cents, "
                "category, occurred_at, status, kind FROM transactions "
                "ORDER BY transaction_id"
            ).fetchall()
        return accounts, transactions

    def _paired_services(self, field_name, changed_value):
        """Clone one seeded fixture, then change exactly one public subscription field."""
        self.assertIn(field_name, ("status", "amount_cents"))
        seed_path = self.fixture_directory / "seed.sqlite"
        seed_service = self.service_class(
            seed_path, user_id="alice", clock=lambda: FIXED_TIME
        )
        seed_service.close()
        baseline_path = self.fixture_directory / "baseline.sqlite"
        variant_path = self.fixture_directory / "variant.sqlite"
        for destination_path in (baseline_path, variant_path):
            with closing(sqlite3.connect(seed_path)) as source_connection:
                with closing(sqlite3.connect(destination_path)) as destination_connection:
                    source_connection.backup(destination_connection)
        with closing(sqlite3.connect(variant_path)) as connection:
            # The identifier comes only from the two literal documented fields above.
            cursor = connection.execute(
                f"UPDATE subscriptions SET {field_name} = ? "
                "WHERE subscription_id = ? AND user_id = ?",
                (changed_value, "sub-video", "alice"),
            )
            self.assertEqual(cursor.rowcount, 1, "The public fixture must contain sub-video")
            connection.commit()
        self.assertEqual(
            self._historical_snapshot(baseline_path),
            self._historical_snapshot(variant_path),
            "Paired fixtures must have identical accounts and complete historical records",
        )
        return (
            self._open_service(baseline_path),
            self._open_service(variant_path),
        )

    def _propose(self, service, intent, parameters=None):
        response = service.propose(
            {"intent": intent, "params": {} if parameters is None else parameters},
            raw_input="Independent V1 permission-boundary acceptance",
        )
        self.assertIsInstance(response, dict, "Public responses must be dictionaries")
        return response

    def _assert_success(self, response, tier):
        # Never include a whole response in diagnostics: pending responses contain secrets.
        self.assertEqual(response.get("status"), "success", "Expected successful public operation")
        self.assertEqual(response.get("tier"), tier, "Permission tier differs from the specification")
        self.assertIsInstance(response.get("data"), dict, "Success must expose documented data")
        return response["data"]

    def _green_results(self, service):
        bill_response = self._propose(service, "analyze_bills", dict(QUERY_PARAMETERS))
        bill_data = self._assert_success(bill_response, "green")
        self.assertEqual(
            bill_data.get("actual_expense_cents"),
            5970,
            "Actual expenditure must remain the documented 990 + 1990 + 2990 history",
        )
        self.assertTrue("categories" in bill_data, "Bill analysis must return documented categories")
        transaction_response = self._propose(
            service, "query_transactions", dict(QUERY_PARAMETERS)
        )
        transaction_data = self._assert_success(transaction_response, "green")
        self.assertTrue("transactions" in transaction_data, "Transactions must use the public result field")
        for business_data in (bill_data, transaction_data):
            for protected_field in PROTECTED_RESULT_FIELDS:
                self.assertFalse(
                    protected_field in business_data,
                    f"Green data must not expose the yellow result field {protected_field}",
                )
        # Compare data, without guessing category/transaction row layouts or removing
        # legitimate historical merchant names, amounts, or payment-status fields.
        return bill_data, transaction_data

    def _assert_same_green_results(self, baseline, variant):
        baseline_bill, baseline_transactions = self._green_results(baseline)
        variant_bill, variant_transactions = self._green_results(variant)
        self.assertEqual(
            baseline_bill["actual_expense_cents"], variant_bill["actual_expense_cents"]
        )
        self.assertEqual(
            baseline_bill["categories"],
            variant_bill["categories"],
            "Historical categories cannot depend on current subscription arrangements",
        )
        self.assertEqual(
            baseline_bill,
            variant_bill,
            "All green bill business data must be independent of current subscription changes",
        )
        self.assertEqual(
            baseline_transactions,
            variant_transactions,
            "All green transaction business data must depend on identical history",
        )

    def _pending_subscription_query(self, service):
        response = self._propose(service, "query_subscriptions")
        self.assertEqual(response.get("status"), "pending", "Subscription reads require explicit confirmation")
        self.assertEqual(response.get("tier"), "yellow", "Subscription queries are yellow")
        for container in (response, response.get("data", {})):
            self.assertIsInstance(container, dict, "Any pre-confirmation data must be a dictionary")
            for protected_field in PROTECTED_RESULT_FIELDS:
                self.assertFalse(
                    protected_field in container,
                    f"Pre-confirmation query must not expose {protected_field}",
                )
        self.assertTrue(
            isinstance(response.get("request_id"), str)
            and isinstance(response.get("confirmation_code"), str),
            "Pending queries must offer the documented exact-confirmation interface",
        )
        return response

    @staticmethod
    def _safe_pending_projection(response):
        """Keep consent output but remove flow fields and all occurrences of its secrets."""
        flow_fields = {"request_id", "confirmation_code", "expires_at"}
        secret_values = (
            response.get("confirmation_code", ""),
            response.get("request_id", ""),
        )

        def clean(value):
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items() if key not in flow_fields}
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, str):
                for secret in secret_values:
                    if secret:
                        value = value.replace(secret, "<flow-value>")
            return value

        return clean(response)

    def _confirm(self, service, pending):
        response = service.confirm(pending["request_id"], pending["confirmation_code"])
        return self._assert_success(response, "yellow")

    def _confirmed_subscriptions(self, service):
        return self._confirm(service, self._pending_subscription_query(service))

    def test_green_business_data_ignores_current_subscription_status(self):
        """US-02/03/29: same history, active versus cancelled subscription."""
        baseline, variant = self._paired_services("status", "cancelled")
        self._assert_same_green_results(baseline, variant)

    def test_green_business_data_ignores_future_subscription_amount(self):
        """Permission section 7: a future-price change does not rewrite past payments."""
        baseline, variant = self._paired_services("amount_cents", 3990)
        self._assert_same_green_results(baseline, variant)
        baseline_data = self._confirmed_subscriptions(baseline)
        variant_data = self._confirmed_subscriptions(variant)
        self.assertEqual(baseline_data.get("future_expected_cents"), 5970)
        self.assertEqual(variant_data.get("future_expected_cents"), 6970)
        self.assertNotEqual(
            baseline_data.get("subscriptions"),
            variant_data.get("subscriptions"),
            "Confirmed subscription output must reflect changed future amounts",
        )

    def test_yellow_query_hides_state_until_exact_confirmation(self):
        """US-04: consent is state-independent; confirmed results expose the difference."""
        baseline, variant = self._paired_services("status", "cancelled")
        baseline_pending = self._pending_subscription_query(baseline)
        variant_pending = self._pending_subscription_query(variant)
        self.assertEqual(
            self._safe_pending_projection(baseline_pending),
            self._safe_pending_projection(variant_pending),
            "Unconfirmed consent output must not disclose the differing current subscription state",
        )
        baseline_data = self._confirm(baseline, baseline_pending)
        variant_data = self._confirm(variant, variant_pending)
        self.assertEqual(baseline_data.get("future_expected_cents"), 5970)
        self.assertEqual(variant_data.get("future_expected_cents"), 2980)
        self.assertTrue("subscriptions" in baseline_data and "subscriptions" in variant_data)
        self.assertNotEqual(
            baseline_data["subscriptions"],
            variant_data["subscriptions"],
            "Confirmed subscription output must distinguish active and cancelled arrangements",
        )

    def test_confirmed_cancellation_preserves_actual_and_transaction_history(self):
        """US-05/29: public cancellation changes future arrangements, not past spending."""
        database_path = self.fixture_directory / "cancel.sqlite"
        service = self._open_service(database_path)
        historical_snapshot = self._historical_snapshot(database_path)
        before_bill, before_transactions = self._green_results(service)
        pending = self._propose(
            service, "cancel_subscription", {"subscription_id": "sub-video"}
        )
        self.assertEqual(pending.get("status"), "pending", "Cancellation requires confirmation")
        self.assertEqual(pending.get("tier"), "yellow")
        with closing(sqlite3.connect(database_path)) as connection:
            status = connection.execute(
                "SELECT status FROM subscriptions WHERE subscription_id = ? AND user_id = ?",
                ("sub-video", "alice"),
            ).fetchone()
        self.assertEqual(status, ("active",), "Unconfirmed cancellation must not modify the subscription")
        self._confirm(service, pending)
        with closing(sqlite3.connect(database_path)) as connection:
            status = connection.execute(
                "SELECT status FROM subscriptions WHERE subscription_id = ? AND user_id = ?",
                ("sub-video", "alice"),
            ).fetchone()
        self.assertEqual(status, ("cancelled",))
        self.assertEqual(self._historical_snapshot(database_path), historical_snapshot)
        after_bill, after_transactions = self._green_results(service)
        self.assertEqual(after_bill, before_bill, "Cancellation cannot alter historical bill data")
        self.assertEqual(after_transactions, before_transactions, "Cancellation cannot alter historical transactions")
        subscription_data = self._confirmed_subscriptions(service)
        self.assertEqual(subscription_data.get("future_expected_cents"), 2980)


def source_hashes():
    """Hash source bytes without exposing or interpreting implementation contents."""
    return {
        source_path.relative_to(REPOSITORY_ROOT).as_posix(): hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest()
        for source_path in sorted((REPOSITORY_ROOT / "src").rglob("*.py"))
    }


def run_acceptance():
    evidence_path = REPOSITORY_ROOT / "evidence" / "v1-independent-acceptance.txt"
    # Append every run: preserve initial failures and any subsequent regression.
    with evidence_path.open("a", encoding="utf-8") as evidence:
        before_hashes = source_hashes()
        started_at = datetime.now(timezone.utc).isoformat()
        evidence.write("\nV1 independent offline acceptance (appended run)\n")
        evidence.write("Author input: AGENTS.md; docs/01,02,05; src/PUBLIC_API.md; tests/README.md.\n")
        evidence.write("No business source, old tests, or external reproduction scripts were read.\n")
        evidence.write("No model calls; all databases are temporary; data/bank.db is untouched.\n")
        evidence.write("Command: & '" + sys.executable + "' -B tests/test_v1_permission_boundary.py\n")
        evidence.write("Started UTC: " + started_at + "\n")
        evidence.write("Test file SHA256: " + hashlib.sha256(Path(__file__).read_bytes()).hexdigest() + "\n")
        evidence.write("Source SHA256 before:\n" + json.dumps(before_hashes, indent=2) + "\n")
        evidence.flush()
        captured_output = io.StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(V1PermissionBoundaryTests)
        result = unittest.TextTestRunner(stream=captured_output, verbosity=2).run(suite)
        after_hashes = source_hashes()
        changed_paths = sorted(
            source_path
            for source_path in set(before_hashes) | set(after_hashes)
            if before_hashes.get(source_path) != after_hashes.get(source_path)
        )
        raw_result = captured_output.getvalue()
        evidence.write("\nRaw unittest result:\n" + raw_result)
        evidence.write("\nSource SHA256 after:\n" + json.dumps(after_hashes, indent=2) + "\n")
        evidence.write("Changed source paths: " + json.dumps(changed_paths) + "\n")
        evidence.write("Finished UTC: " + datetime.now(timezone.utc).isoformat() + "\n")
        evidence.write(
            f"Summary: tests={result.testsRun}; failures={len(result.failures)}; "
            f"errors={len(result.errors)}; skipped={len(result.skipped)}; "
            f"exit_code={0 if result.wasSuccessful() else 1}\n"
        )
    print(raw_result, end="")
    print("Changed source paths: " + json.dumps(changed_paths))
    print("Evidence: " + str(evidence_path))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(run_acceptance())
