"""Checks on .bestpractices.json, the OpenSSF Best Practices self-attestation.

The badge app reads this file from the repository root and uses it to fill
in the edit form for the project entry. It is the reviewable record of the
answers behind the badge, so it has to stay in step with the repository:
a justification that points at a file or a workflow that has since moved
would make the attestation wrong.

The rules below are a snapshot of the badge app's Passing level, taken from
``criteria/criteria.yml`` (level "0") in ossf/best-practices-badge. Refresh
it when the badge app changes its criteria; the badge app's own
docs/criteria.yml is the source of truth.
"""

import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = REPO_ROOT / ".bestpractices.json"

METADATA_FIELDS = {
    "name",
    "description",
    "license",
    "implementation_languages",
    "homepage_url",
    "repo_url",
}

# criterion key -> (category, na_allowed, met_url_required)
CRITERIA = {
    "build": ("MUST", True, False),
    "build_common_tools": ("SUGGESTED", True, False),
    "build_floss_tools": ("SHOULD", True, False),
    "contribution": ("MUST", False, True),
    "contribution_requirements": ("SHOULD", False, True),
    "crypto_call": ("SHOULD", True, False),
    "crypto_floss": ("MUST", True, False),
    "crypto_keylength": ("MUST", True, False),
    "crypto_password_storage": ("MUST", True, False),
    "crypto_pfs": ("SHOULD", True, False),
    "crypto_published": ("MUST", True, False),
    "crypto_random": ("MUST", True, False),
    "crypto_weaknesses": ("SHOULD", True, False),
    "crypto_working": ("MUST", True, False),
    "delivery_mitm": ("MUST", False, False),
    "delivery_unsigned": ("MUST", False, False),
    "description_good": ("MUST", False, False),
    "discussion": ("MUST", False, False),
    "documentation_basics": ("MUST", True, False),
    "documentation_interface": ("MUST", True, False),
    "dynamic_analysis": ("SUGGESTED", False, False),
    "dynamic_analysis_enable_assertions": ("SUGGESTED", False, False),
    "dynamic_analysis_fixed": ("MUST", True, False),
    "dynamic_analysis_unsafe": ("SUGGESTED", True, False),
    "english": ("SHOULD", False, False),
    "enhancement_responses": ("SHOULD", False, False),
    "floss_license": ("MUST", False, False),
    "floss_license_osi": ("SUGGESTED", False, False),
    "interact": ("MUST", False, False),
    "know_common_errors": ("MUST", False, False),
    "know_secure_design": ("MUST", False, False),
    "license_location": ("MUST", False, True),
    "maintained": ("MUST", False, False),
    "no_leaked_credentials": ("MUST", False, False),
    "release_notes": ("MUST", True, True),
    "release_notes_vulns": ("MUST", True, False),
    "repo_distributed": ("SUGGESTED", False, False),
    "repo_interim": ("MUST", False, False),
    "repo_public": ("MUST", False, False),
    "repo_track": ("MUST", False, False),
    "report_archive": ("MUST", False, True),
    "report_process": ("MUST", False, True),
    "report_responses": ("MUST", False, False),
    "report_tracker": ("SHOULD", False, False),
    "sites_https": ("MUST", False, False),
    "static_analysis": ("MUST", True, False),
    "static_analysis_common_vulnerabilities": ("SUGGESTED", True, False),
    "static_analysis_fixed": ("MUST", True, False),
    "static_analysis_often": ("SUGGESTED", True, False),
    "test": ("MUST", False, False),
    "test_continuous_integration": ("SUGGESTED", False, False),
    "test_invocation": ("SHOULD", False, False),
    "test_most": ("SUGGESTED", False, False),
    "test_policy": ("MUST", False, False),
    "tests_are_added": ("MUST", False, False),
    "tests_documented_added": ("SUGGESTED", False, False),
    "version_semver": ("SUGGESTED", False, False),
    "version_tags": ("SUGGESTED", False, False),
    "version_unique": ("MUST", False, False),
    "vulnerabilities_critical_fixed": ("SHOULD", False, False),
    "vulnerabilities_fixed_60_days": ("MUST", False, False),
    "vulnerability_report_private": ("MUST", True, True),
    "vulnerability_report_process": ("MUST", False, True),
    "vulnerability_report_response": ("MUST", True, False),
    "warnings": ("MUST", True, False),
    "warnings_fixed": ("MUST", True, False),
    "warnings_strict": ("SUGGESTED", True, False),
}

VALID_STATUSES = {"Met", "Unmet", "N/A", "?"}

# A justification must point somewhere for the criteria that ask for a URL.
URL_PATTERN = re.compile(r"https?://[^/. ]+\.[^ ]")

# Paths inside the repository that a justification may refer to.
BLOB_URL_PATTERN = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/blob/main/(?P<path>[^#?]+)"
)


class BestPracticesJsonTests(unittest.TestCase):
    """The self-attestation must stay valid and must stay in step with the repo."""

    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    def test_file_is_a_flat_object_of_strings(self):
        for key, value in self.data.items():
            with self.subTest(key=key):
                self.assertIsInstance(key, str)
                self.assertIsInstance(value, str)

    def test_every_passing_criterion_is_answered(self):
        for key in CRITERIA:
            with self.subTest(criterion=key):
                self.assertIn(key + "_status", self.data)
                self.assertIn(key + "_justification", self.data)

    def test_no_unknown_fields(self):
        known = METADATA_FIELDS | {
            key + suffix for key in CRITERIA for suffix in ("_status", "_justification")
        }
        self.assertEqual(set(self.data) - known, set())

    def test_metadata_fields_are_filled_in(self):
        for field in METADATA_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(self.data[field].strip())

    def test_statuses_are_valid(self):
        for key in CRITERIA:
            with self.subTest(criterion=key):
                self.assertIn(self.data[key + "_status"], VALID_STATUSES)

    def test_na_is_only_used_where_it_is_allowed(self):
        for key, (_category, na_allowed, _url) in CRITERIA.items():
            if self.data[key + "_status"] == "N/A":
                with self.subTest(criterion=key):
                    self.assertTrue(na_allowed, "N/A is not allowed here")

    def test_na_always_explains_itself(self):
        for key in CRITERIA:
            if self.data[key + "_status"] == "N/A":
                with self.subTest(criterion=key):
                    self.assertTrue(self.data[key + "_justification"].strip())

    def test_met_criteria_that_need_a_url_have_one(self):
        for key, (_category, _na, url_required) in CRITERIA.items():
            if url_required and self.data[key + "_status"] == "Met":
                with self.subTest(criterion=key):
                    self.assertRegex(self.data[key + "_justification"], URL_PATTERN)

    def test_unmet_should_criteria_explain_themselves(self):
        for key, (category, _na, _url) in CRITERIA.items():
            if category == "SHOULD" and self.data[key + "_status"] == "Unmet":
                with self.subTest(criterion=key):
                    self.assertTrue(self.data[key + "_justification"].strip())

    def test_must_criteria_are_met_or_not_applicable(self):
        for key, (category, _na, _url) in CRITERIA.items():
            if category == "MUST":
                with self.subTest(criterion=key):
                    self.assertIn(self.data[key + "_status"], {"Met", "N/A"})

    def test_referenced_repository_files_exist(self):
        """A justification must not point at a file that has moved or gone."""
        for key in CRITERIA:
            justification = self.data[key + "_justification"]
            for url in re.findall(r"https?://\S+", justification):
                match = BLOB_URL_PATTERN.match(url)
                if match:
                    with self.subTest(criterion=key, path=match.group("path")):
                        self.assertTrue(
                            (REPO_ROOT / match.group("path")).exists(),
                            f"{match.group('path')} is referenced but missing",
                        )

    def test_the_repository_url_is_the_one_scorecard_queries(self):
        """Scorecard looks the entry up by exactly this URL."""
        expected = "https://github.com/AlexMultiAgent/dify-plugin-text-fitter"
        self.assertEqual(self.data["repo_url"], expected)
        self.assertEqual(self.data["homepage_url"], expected)
        self.assertEqual(
            urlparse(self.data["repo_url"]).path,
            "/AlexMultiAgent/dify-plugin-text-fitter",
        )


if __name__ == "__main__":
    unittest.main()
