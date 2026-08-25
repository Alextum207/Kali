import httpx
import pytest

from app.robots import fetch_robots_parser


@pytest.mark.asyncio
async def test_fetch_robots_parser_disallows_blocked_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /checkout/\n")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        parser = await fetch_robots_parser("https://example.com/", client)

    assert parser.can_fetch("*", "https://example.com/products") is True
    assert parser.can_fetch("*", "https://example.com/checkout/step1") is False


@pytest.mark.asyncio
async def test_fetch_robots_parser_disallows_entire_site():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        parser = await fetch_robots_parser("https://example.com/", client)

    assert parser.can_fetch("*", "https://example.com/") is False


@pytest.mark.asyncio
async def test_fetch_robots_parser_fails_open_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        parser = await fetch_robots_parser("https://example.com/", client)

    assert parser.can_fetch("*", "https://example.com/anything") is True


@pytest.mark.asyncio
async def test_fetch_robots_parser_fails_open_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        parser = await fetch_robots_parser("https://example.com/", client)

    assert parser.can_fetch("*", "https://example.com/anything") is True
