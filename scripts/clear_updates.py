"""Clear all update records from Firestore so you can test with fresh data.

Usage:
    python -m scripts.clear_updates
"""

import asyncio

from google.cloud import firestore


async def main():
    client = firestore.AsyncClient()
    collection = client.collection("updates")

    count = 0
    async for doc in collection.stream():
        await doc.reference.delete()
        count += 1
        print(f"  Deleted update: {doc.id}")

    print(f"\nDone — deleted {count} update(s).")


if __name__ == "__main__":
    asyncio.run(main())
