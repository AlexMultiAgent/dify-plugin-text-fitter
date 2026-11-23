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


class TraditionalChineseTests(unittest.TestCase):
    """Traditional Chinese shares the CJK code path with Simplified Chinese.

    These cases pin that path down: the zh_Hant interface is translated, so
    the processing side has to keep up.
    """

    TEXT = (
        "臺灣位於東亞，氣候溫暖潮濕。臺北是臺灣的首都，也是最大的城市。"
        "高雄則以港口和工業聞名。這裡的人們說著華語，也使用繁體中文。"
        "這是一個測試句子，用來驗證繁體中文的處理效果。最後一句話。"
    )

    def test_traditional_chinese_sentences_split_on_cjk_punctuation(self):
        sentences = _split_sentences(
            "臺灣位於東亞，氣候溫暖潮濕。臺北是臺灣的首都。最後一句話。"
        )

        self.assertEqual(
            sentences,
            ["臺灣位於東亞，氣候溫暖潮濕。", "臺北是臺灣的首都。", "最後一句話。"],
        )

    def test_traditional_chinese_quotes_stay_with_their_sentence(self):
        sentences = _split_sentences(
            "他說：「你好。」然後離開了。她讀了《紅樓夢》……這是『經典』。"
        )

        self.assertEqual(
            sentences,
            [
                "他說：「你好。」",
                "然後離開了。",
                "她讀了《紅樓夢》……",
                "這是『經典』。",
            ],
        )

    def test_traditional_chinese_trimming_keeps_original_sentences(self):
        result, algorithm = _extract_key_sentences(
            self.TEXT, max_chars=40, method="greedy"
        )

        self.assertEqual(algorithm, "greedy")
        self.assertLessEqual(len(result), 40)
        self.assertEqual(
            result,
            "臺灣位於東亞，氣候溫暖潮濕。臺北是臺灣的首都，也是最大的城市。最後一句話。",
        )

    def test_traditional_chinese_mmr_selection_stays_within_budget(self):
        result, algorithm = _extract_key_sentences(
            self.TEXT, max_chars=40, method="mmr"
        )

        self.assertEqual(algorithm, "mmr")
        self.assertLessEqual(len(result), 40)
        # Selected spans must be original sentences, never rewritten text.
        for sentence in _split_sentences(result):
            self.assertIn(sentence, self.TEXT)

    def test_traditional_chinese_passthrough_is_unchanged(self):
        tool = FakeSmartTrimTool.__new__(FakeSmartTrimTool)
        text = "繁體中文測試。"

        messages = list(tool._invoke({"text": text, "max_chars": 100}))

        self.assertEqual(messages[0], ("text", text))
        variables = {
            message[1]: message[2] for message in messages if message[0] == "var"
        }
        self.assertEqual(variables["algorithm"], "passthrough")
        self.assertFalse(variables["was_trimmed"])


if __name__ == "__main__":
    unittest.main()
