import asyncio
import json
from camoufox.async_api import AsyncCamoufox

async def get_listing(item_id: str):
    async with AsyncCamoufox(headless=True) as browser:
        page = await browser.new_page()

        coords = {}

        async def handle_response(response):
            if "graphql" in response.url and "UserRelatedItem" in response.url:
                try:
                    body = await response.json()
                    item = body.get("data", {}).get("item", {})
                    if item.get("latitude"):
                        coords["lat"] = item["latitude"]
                        coords["lng"] = item["longitude"]
                except Exception:
                    pass

        page.on("response", handle_response)

        url = f"https://bina.az/items/{item_id}"
        await page.goto(url, wait_until="load", timeout=60000)
        await page.wait_for_function("() => document.title !== 'Just a moment...'", timeout=30000)
        await page.wait_for_timeout(3000)

        lat = coords.get("lat")
        lng = coords.get("lng")

        print(f"Item ID:   {item_id}")
        print(f"Latitude:  {lat}")
        print(f"Longitude: {lng}")
        if lat and lng:
            print(f"Maps link: https://www.google.com/maps?q={lat},{lng}")

        return coords

import sys
item_id = sys.argv[1] if len(sys.argv) > 1 else "6441221"
asyncio.run(get_listing(item_id))
