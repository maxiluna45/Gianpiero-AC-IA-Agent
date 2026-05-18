from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

import httpx

from ac_mcp.config import tavily_api_key

_FORUM_DOMAINS = {
    "overtake.gg",
    "racedepartment.com",
    "steamcommunity.com",
    "reddit.com",
    "assettocorsa.net",
    "gtplanet.net",
}


def _compact(value: str) -> str:
    lowered = value.lower().strip()
    cleaned = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(cleaned.split())


def _short_track_tokens(track: str) -> list[str]:
    token = _compact(track)
    if not token:
        return []

    words = [w for w in token.split() if w not in {"autodrom", "autodromo", "circuit", "track"}]
    joined = " ".join(words)
    output = [token]
    if joined and joined != token:
        output.append(joined)
    if words:
        output.append(words[-1])

    unique: list[str] = []
    for row in output:
        if row and row not in unique:
            unique.append(row)
    return unique


def _car_tokens(car: str) -> list[str]:
    token = _compact(car)
    if not token:
        return []

    compact = token.replace(" ", "")
    output = [token]
    if compact and compact != token:
        output.append(compact)

    unique: list[str] = []
    for row in output:
        if row and row not in unique:
            unique.append(row)
    return unique


def _build_queries(car: str, track: str, symptom: str) -> list[str]:
    car_values = _car_tokens(car) or ["formula car"]
    track_values = _short_track_tokens(track) or ["track"]
    symptom_value = _compact(symptom) if symptom.strip() else "setup guide"

    base = f"assetto corsa {car_values[0]} {track_values[0]} setup {symptom_value}"
    queries = [
        f"{base} original",
        f"{base} forum",
        f"{base} race setup",
        f"{base} site:overtake.gg",
        f"{base} site:racedepartment.com",
        f"{base} site:steamcommunity.com",
        f"{base} site:reddit.com",
        f"{base} -competizione -acc",
    ]

    if len(track_values) > 1:
        queries.append(f"assetto corsa {car_values[0]} {track_values[1]} setup forum")
    if len(car_values) > 1:
        queries.append(f"assetto corsa {car_values[1]} {track_values[0]} setup")

    unique: list[str] = []
    for item in queries:
        cleaned = " ".join(item.split())
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique


def _build_track_queries(track: str) -> list[str]:
    tokens = _short_track_tokens(track) or [_compact(track) or "track"]
    base_track = tokens[0]
    queries = [
        f"{base_track} circuit layout braking zones",
        f"{base_track} track guide corners overtaking",
        f"assetto corsa {base_track} track guide",
        f"{base_track} onboard lap guide",
    ]
    if len(tokens) > 1:
        queries.append(f"{tokens[1]} circuit layout braking")

    unique: list[str] = []
    for item in queries:
        cleaned = " ".join(item.split())
        if cleaned and cleaned not in unique:
            unique.append(cleaned)
    return unique


def _clean_html_text(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def _unwrap_duckduckgo_url(url: str) -> str:
    decoded = html.unescape(url)
    if decoded.startswith("//"):
        decoded = "https:" + decoded
    if decoded.startswith("/"):
        decoded = "https://duckduckgo.com" + decoded

    parsed = urlparse(decoded)
    if "duckduckgo.com" not in parsed.netloc.lower():
        return decoded

    query = parse_qs(parsed.query)
    wrapped = query.get("uddg", [""])[0]
    if wrapped:
        return unquote(wrapped)
    return decoded


def _extract_duckduckgo_results(body: str, max_results: int) -> list[dict[str, Any]]:
    anchors = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets_raw = re.findall(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(.*?)</div>',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets: list[str] = []
    for left, right in snippets_raw:
        snippets.append(_clean_html_text(left or right))

    items: list[dict[str, Any]] = []
    for index, (href, title_html) in enumerate(anchors):
        resolved = _unwrap_duckduckgo_url(href)
        if not resolved.lower().startswith("http"):
            continue

        title = _clean_html_text(title_html)
        snippet = snippets[index] if index < len(snippets) else ""
        items.append(
            {
                "title": title or "DuckDuckGo result",
                "url": resolved,
                "snippet": snippet,
                "score": 0.5,
                "source": "duckduckgo",
            }
        )
        if len(items) >= max(1, max_results):
            break

    return items


def _duckduckgo_search(query: str, max_results: int) -> list[dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/"
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            url,
            data={
                "q": query,
                "kl": "wt-wt",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
            },
        )
        response.raise_for_status()
        body = response.text

    items = _extract_duckduckgo_results(body=body, max_results=max_results)
    if items:
        return items

    # Fallback to instant answer API if HTML endpoint yields no parsable results.
    instant_url = "https://api.duckduckgo.com/"
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            instant_url,
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
        )
        response.raise_for_status()
        payload = response.json()

    fallback_items: list[dict[str, Any]] = []

    abstract_url = str(payload.get("AbstractURL", "") or "")
    abstract_text = str(payload.get("AbstractText", "") or "")
    heading = str(payload.get("Heading", "") or "")
    if abstract_url and abstract_text:
        fallback_items.append(
            {
                "title": heading or "DuckDuckGo result",
                "url": abstract_url,
                "snippet": abstract_text,
                "score": 0.6,
                "source": "duckduckgo",
            }
        )

    related = payload.get("RelatedTopics", [])
    for topic in related:
        if isinstance(topic, dict) and "Topics" in topic:
            for child in topic.get("Topics", []):
                text = str(child.get("Text", "") or "")
                link = str(child.get("FirstURL", "") or "")
                if text and link:
                    fallback_items.append(
                        {
                            "title": text.split(" - ", maxsplit=1)[0],
                            "url": link,
                            "snippet": text,
                            "score": 0.5,
                            "source": "duckduckgo",
                        }
                    )
        elif isinstance(topic, dict):
            text = str(topic.get("Text", "") or "")
            link = str(topic.get("FirstURL", "") or "")
            if text and link:
                fallback_items.append(
                    {
                        "title": text.split(" - ", maxsplit=1)[0],
                        "url": link,
                        "snippet": text,
                        "score": 0.5,
                        "source": "duckduckgo",
                    }
                )

    return fallback_items[: max(1, max_results)]


def _tavily_search(query: str, max_results: int, api_key: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=20.0) as client:
        response = client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "max_results": max(1, min(max_results, 10)),
                "include_answer": False,
                "include_raw_content": False,
            },
        )
        response.raise_for_status()
        payload = response.json()

    items: list[dict[str, Any]] = []
    for row in payload.get("results", []):
        items.append(
            {
                "title": str(row.get("title", "") or ""),
                "url": str(row.get("url", "") or ""),
                "snippet": str(row.get("content", "") or ""),
                "score": float(row.get("score", 0.0) or 0.0),
                "source": "tavily",
            }
        )

    return items


def _score_item(item: dict[str, Any], car: str, track: str) -> float:
    title = _compact(str(item.get("title", "") or ""))
    snippet = _compact(str(item.get("snippet", "") or ""))
    url = str(item.get("url", "") or "")
    haystack = f"{title} {snippet}"

    score = float(item.get("score", 0.0) or 0.0)

    for token in _car_tokens(car):
        if token and token in haystack:
            score += 0.25

    for token in _short_track_tokens(track):
        if token and token in haystack:
            score += 0.2

    netloc = urlparse(url).netloc.lower()
    if any(netloc.endswith(domain) or f".{domain}" in netloc for domain in _FORUM_DOMAINS):
        score += 0.2

    if "competizione" in haystack or " acc " in f" {haystack} ":
        score -= 0.2

    return score


def _collect_multi_query_results(
    queries: list[str],
    max_results: int,
    provider: str,
    car: str,
    track: str,
) -> tuple[list[dict[str, Any]], str]:
    use_tavily = provider in {"tavily", "auto"} and bool(tavily_api_key())
    selected = "tavily" if use_tavily else "duckduckgo"

    seen_urls: set[str] = set()
    merged: list[dict[str, Any]] = []
    per_query_limit = max(3, min(8, max_results))

    for query in queries:
        if len(merged) >= max_results * 3:
            break

        rows = (
            _tavily_search(query=query, max_results=per_query_limit, api_key=tavily_api_key())
            if use_tavily
            else _duckduckgo_search(query=query, max_results=per_query_limit)
        )

        for row in rows:
            url = str(row.get("url", "") or "").strip()
            if not url:
                continue
            normalized_url = url.split("#", maxsplit=1)[0]
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            enriched = dict(row)
            enriched["query"] = query
            enriched["score"] = _score_item(enriched, car=car, track=track)
            merged.append(enriched)

    merged.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    return merged[: max(1, max_results)], selected


def _extract_track_traits(text: str) -> dict[str, float]:
    hay = _compact(text)

    def hit(*keywords: str) -> float:
        score = 0.0
        for keyword in keywords:
            key = _compact(keyword)
            if key and key in hay:
                score += 1.0
        return score

    return {
        "long_straight": hit("long straight", "straightaway", "top speed", "high speed") ,
        "heavy_braking": hit("heavy braking", "hard braking", "braking zone", "late braking"),
        "chicane": hit("chicane"),
        "slow_corners": hit("hairpin", "slow corner", "tight corner"),
        "high_speed_corners": hit("fast corner", "high-speed corner", "sweeper"),
        "curb_sensitivity": hit("curb", "kerb", "bumpy", "bump"),
        "overtaking": hit("overtake", "overtaking", "passing"),
    }


def get_circuit_info(
    track: str,
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    if not track.strip():
        return {
            "track": track,
            "provider": "error",
            "queries_tried": [],
            "sources": [],
            "traits": {},
            "summary": "track is required",
            "error": "track is required",
        }

    limit = max(1, min(max_results, 10))
    queries = _build_track_queries(track)

    try:
        candidates, selected = _collect_multi_query_results(
            queries=queries,
            max_results=limit,
            provider=provider,
            car="track",
            track=track,
        )
    except Exception as exc:
        return {
            "track": track,
            "provider": "error",
            "queries_tried": queries,
            "sources": [],
            "traits": {},
            "summary": "",
            "error": str(exc),
        }

    traits: dict[str, float] = {
        "long_straight": 0.0,
        "heavy_braking": 0.0,
        "chicane": 0.0,
        "slow_corners": 0.0,
        "high_speed_corners": 0.0,
        "curb_sensitivity": 0.0,
        "overtaking": 0.0,
    }

    sources: list[dict[str, Any]] = []
    for row in candidates[: min(4, len(candidates))]:
        url = str(row.get("url", "") or "")
        title = str(row.get("title", "") or "")
        snippet = str(row.get("snippet", "") or "")

        details = fetch_reference(url=url, max_chars=5000)
        text = str(details.get("text", "") or "")
        combined = f"{snippet} {text}"

        extracted = _extract_track_traits(combined)
        for key, value in extracted.items():
            traits[key] += value

        sources.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "fetch_error": str(details.get("error", "") or ""),
            }
        )

    highlights = [key for key, value in traits.items() if value >= 2.0]
    summary = ""
    if highlights:
        summary = "Track traits detected: " + ", ".join(highlights)
    else:
        summary = "No strong traits detected from fetched sources"

    return {
        "track": track,
        "provider": selected,
        "queries_tried": queries,
        "sources": sources,
        "traits": traits,
        "summary": summary,
        "error": "",
    }


def search_references(
    car: str,
    track: str,
    symptom: str = "",
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    symptom_token = symptom.strip() if symptom.strip() else "setup guide"
    limit = max(1, min(max_results, 10))
    queries = _build_queries(car=car, track=track, symptom=symptom_token)

    try:
        items, selected = _collect_multi_query_results(
            queries=queries,
            max_results=limit,
            provider=provider,
            car=car,
            track=track,
        )
    except Exception as exc:
        return {
            "provider": "error",
            "query": queries[0] if queries else "",
            "queries_tried": queries,
            "count": 0,
            "items": [],
            "error": str(exc),
        }

    return {
        "provider": selected,
        "query": queries[0] if queries else "",
        "queries_tried": queries,
        "count": len(items),
        "items": items,
        "error": "",
    }


def search_base_setups(
    car: str,
    track: str,
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    return search_references(
        car=car,
        track=track,
        symptom="baseline setup default setup",
        max_results=max_results,
        provider=provider,
    )


def fetch_reference(url: str, max_chars: int = 7000) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            content_type = str(response.headers.get("content-type", "")).lower()
            body = response.text
    except Exception as exc:
        return {
            "url": url,
            "title": "",
            "text": "",
            "content_type": "",
            "error": str(exc),
        }

    title = ""
    text = ""

    if "application/json" in content_type:
        try:
            parsed = json.loads(body)
            text = json.dumps(parsed, ensure_ascii=True, indent=2)
        except json.JSONDecodeError:
            text = body
    else:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            title = html.unescape(title_match.group(1).strip())

        cleaned = re.sub(r"<script[\\s\\S]*?</script>", " ", body, flags=re.IGNORECASE)
        cleaned = re.sub(r"<style[\\s\\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        text = cleaned

    return {
        "url": url,
        "title": title,
        "text": text[: max(500, max_chars)],
        "content_type": content_type,
        "error": "",
    }
