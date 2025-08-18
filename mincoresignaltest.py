import httpx
import asyncio

API_KEY = "IBMeY0rFKwHFj4fuk3JPPPakfG5fg2ow"  # paste your key
BASE = "https://api.coresignal.com/cdapi"


async def enrich(domain: str):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{BASE}/v2/company_clean/enrich",
            params={"website": domain},
            headers={
                "accept": "application/json",
                "apikey": API_KEY,
            },
        )
        r.raise_for_status()
        return r.json()


if __name__ == "__main__":
    print(asyncio.run(enrich("thermofisher.com")))
