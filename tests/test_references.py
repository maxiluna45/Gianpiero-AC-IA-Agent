from __future__ import annotations

import unittest
from unittest.mock import patch

from ac_mcp.references import _build_queries, _extract_duckduckgo_results, get_circuit_info, search_references


class ReferencesTests(unittest.TestCase):
    def test_build_queries_includes_forum_and_sites(self) -> None:
        queries = _build_queries(car="tatuus fa1", track="autodrom most", symptom="aggressive setup")

        self.assertTrue(any("site:overtake.gg" in q for q in queries))
        self.assertTrue(any("site:racedepartment.com" in q for q in queries))
        self.assertTrue(any("forum" in q for q in queries))
        self.assertTrue(any(" most " in f" {q} " for q in queries))

    def test_extract_duckduckgo_results_parses_html(self) -> None:
        body = """
        <html><body>
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fovertake.gg%2Fthreads%2Fabc">Tatuus setup thread</a>
          <div class="result__snippet">Useful baseline for Most circuit</div>
        </body></html>
        """

        rows = _extract_duckduckgo_results(body=body, max_results=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://overtake.gg/threads/abc")
        self.assertIn("Most", rows[0]["snippet"])

    @patch("ac_mcp.references.tavily_api_key", return_value="")
    @patch("ac_mcp.references._duckduckgo_search")
    def test_search_references_aggregates_and_deduplicates(self, mock_search, _mock_tavily) -> None:
        def fake_search(query: str, max_results: int):
            if "site:overtake.gg" in query:
                return [
                    {
                        "title": "Tatuus Most setup",
                        "url": "https://overtake.gg/threads/most-setup",
                        "snippet": "Aggressive setup for Most",
                        "score": 0.5,
                        "source": "duckduckgo",
                    }
                ]
            return [
                {
                    "title": "General setup",
                    "url": "https://example.com/setup",
                    "snippet": "Assetto Corsa tatuusfa1 most",
                    "score": 0.4,
                    "source": "duckduckgo",
                },
                {
                    "title": "Duplicate",
                    "url": "https://example.com/setup",
                    "snippet": "duplicate row",
                    "score": 0.3,
                    "source": "duckduckgo",
                },
            ]

        mock_search.side_effect = fake_search

        result = search_references(
            car="tatuusfa1",
            track="autodrom most",
            symptom="aggressive",
            max_results=5,
            provider="auto",
        )

        self.assertEqual(result["provider"], "duckduckgo")
        self.assertGreaterEqual(result["count"], 2)
        urls = [item["url"] for item in result["items"]]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(any("overtake.gg" in url for url in urls))
        self.assertTrue(len(result.get("queries_tried", [])) >= 3)

    @patch("ac_mcp.references.fetch_reference")
    @patch("ac_mcp.references._collect_multi_query_results")
    def test_get_circuit_info_extracts_traits(self, mock_collect, mock_fetch) -> None:
        mock_collect.return_value = (
            [
                {
                    "title": "Most guide",
                    "url": "https://example.com/most-guide",
                    "snippet": "Track has long straight and heavy braking into chicane",
                    "score": 1.0,
                    "source": "duckduckgo",
                }
            ],
            "duckduckgo",
        )
        mock_fetch.return_value = {
            "url": "https://example.com/most-guide",
            "title": "Most guide",
            "text": "Long straight, heavy braking and one sharp chicane. Good overtaking opportunities.",
            "content_type": "text/html",
            "error": "",
        }

        result = get_circuit_info(track="autodrom most", max_results=5, provider="auto")

        self.assertEqual(result["provider"], "duckduckgo")
        self.assertEqual(result["error"], "")
        self.assertGreater(result["traits"]["long_straight"], 0)
        self.assertGreater(result["traits"]["heavy_braking"], 0)
        self.assertGreater(result["traits"]["chicane"], 0)
        self.assertGreaterEqual(len(result["sources"]), 1)


if __name__ == "__main__":
    unittest.main()
