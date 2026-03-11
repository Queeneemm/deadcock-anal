import logging
from pathlib import Path

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


class AssetsClient:
    def __init__(self, base_url: str, cache_dir: Path, timeout_seconds: int):
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def _download_asset(self, remote_path: str, local_name: str) -> Path:
        target = self.cache_dir / local_name
        if target.exists():
            return target
        try:
            response = await self.client.get(remote_path)
            response.raise_for_status()
            target.write_bytes(response.content)
            return target
        except Exception:
            logger.exception("Не удалось скачать ассет: %s", remote_path)
            return self.get_placeholder_asset()

    def get_placeholder_asset(self) -> Path:
        placeholder = self.cache_dir / "placeholder.png"
        if not placeholder.exists():
            Image.new("RGBA", (512, 512), (30, 30, 35, 255)).save(placeholder)
        return placeholder

    # TODO: сверить финальные пути ассетов c актуальной Assets API.
    async def get_hero_assets(self, hero_name: str) -> Path:
        safe = hero_name.lower().replace(" ", "_")
        return await self._download_asset(f"heroes/{safe}.png", f"hero_{safe}.png")

    async def get_item_asset(self, item_name: str) -> Path:
        safe = item_name.lower().replace(" ", "_")
        return await self._download_asset(f"items/{safe}.png", f"item_{safe}.png")
