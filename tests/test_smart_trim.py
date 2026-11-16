import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from tools import smart_trim
from tools.smart_trim import SmartTrimTool, _extract_key_sentences, _split_sentences


class FakeSmartTrimTool(SmartTrimTool):
    def create_text_message(self, text):
        return ("text", text)

    def create_variable_message(self, name, value):
        return ("var", name, value)

    def create_json_message(self, value):
        return ("json", value)


class SmartTrimSentenceBoundaryTests(unittest.TestCase):
    def test_trimmed_english_preserves_spaces_between_selected_sentences(self):
        text = "First sentence. Second sentence. Third sentence."

        result, algorithm = _extract_key_sentences(text, max_chars=31, method="greedy")

        self.assertEqual(result, "First sentence. Third sentence.")
        self.assertEqual(algorithm, "greedy")

    def test_trimmed_markdown_preserves_line_boundaries(self):
        text = "Heading\n- item one\n- item two"

        result, algorithm = _extract_key_sentences(text, max_chars=25, method="greedy")

        self.assertEqual(result, "Heading\n- item two")
        self.assertEqual(algorithm, "greedy")

    def test_japanese_closing_quote_stays_with_its_sentence(self):
        text = "「最初の文です。」次の文です。"

        sentences = _split_sentences(text)

        self.assertEqual(sentences, ["「最初の文です。」", "次の文です。"])

    def test_chinese_closing_quote_stays_with_its_sentence(self):
        text = "他说：“你好。”然后离开了。"

        result, algorithm = _extract_key_sentences(text, max_chars=8, method="greedy")

        self.assertEqual(result, "他说：“你好。”")
        self.assertEqual(algorithm, "greedy")

    def test_us_initialism_does_not_create_false_sentence_boundary(self):
        text = "The U.S. Government issued guidance. Next sentence."

        sentences = _split_sentences(text)

        self.assertEqual(
            sentences,
            ["The U.S. Government issued guidance. ", "Next sentence."],
        )

    def test_personal_middle_initial_does_not_create_false_boundary(self):
        text = "John F. Kennedy spoke today. The crowd listened."

        sentences = _split_sentences(text)

        self.assertEqual(
            sentences,
            ["John F. Kennedy spoke today. ", "The crowd listened."],
        )

    def test_english_closing_quote_stays_with_its_sentence(self):
        text = 'He said "Hello." Then he left.'

        sentences = _split_sentences(text)

        self.assertEqual(sentences, ['He said "Hello." ', "Then he left."])

    def test_decimal_number_does_not_create_sentence_boundary(self):
        text = "The value is 3.14 in this example. Next sentence."

        sentences = _split_sentences(text)

        self.assertEqual(
            sentences,
            ["The value is 3.14 in this example. ", "Next sentence."],
        )

    def test_crlf_line_boundaries_are_preserved(self):
        text = "Heading\r\n- item one\r\n- item two"

        result, algorithm = _extract_key_sentences(text, max_chars=25, method="greedy")

        self.assertEqual(result, "Heading\r\n- item two")
        self.assertEqual(algorithm, "greedy")

    def test_trimmed_output_never_exceeds_requested_character_limit(self):
        samples = [
            "First sentence. Second sentence. Third sentence.",
            "Heading\n\nA paragraph. Another paragraph.",
            "「最初の文です。」次の文です。",
            "A" * 100,
        ]

        for limit in (1, 5, 10, 20, 30):
            for text in samples:
                with self.subTest(limit=limit, text=text):
                    result, _algorithm = _extract_key_sentences(text, limit)
                    self.assertLessEqual(len(result), limit)


class SmartTrimFailureTests(unittest.TestCase):
    def test_algorithm_failure_returns_single_safe_truncation(self):
        tool = FakeSmartTrimTool.__new__(FakeSmartTrimTool)

        stderr = io.StringIO()
        with (
            patch.object(
                smart_trim,
                "_extract_key_sentences",
                side_effect=RuntimeError("simulated failure"),
            ),
            redirect_stderr(stderr),
        ):
            messages = list(tool._invoke({"text": "A" * 100, "max_chars": 10}))

        self.assertEqual(len(messages), 7)
        self.assertEqual(messages[0][0], "text")
        self.assertLessEqual(len(messages[0][1]), 10)
        variables = {
            message[1]: message[2] for message in messages if message[0] == "var"
        }
        json_messages = [message for message in messages if message[0] == "json"]
        self.assertEqual(variables["algorithm"], "error_truncation")
        self.assertTrue(variables["was_trimmed"])
        self.assertNotIn("error", variables)
        self.assertEqual(len(json_messages), 1)
        self.assertNotIn("error", json_messages[0][1])
        self.assertIn("RuntimeError: simulated failure", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
