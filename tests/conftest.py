import sys
from pathlib import Path

import pytest


PLUGIN_PARENT = Path(__file__).resolve().parents[2]
if str(PLUGIN_PARENT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_PARENT))


@pytest.fixture
def assert_temporary_image():
    created_paths: set[Path] = set()

    def assert_image(result, value: str, expected_bytes: bytes) -> Path:
        image_path = Path(value)
        assert image_path in result.temporary_files
        assert image_path.is_file()
        assert image_path.read_bytes() == expected_bytes
        assert not value.startswith("base64://")
        created_paths.add(image_path)
        return image_path

    yield assert_image

    for image_path in created_paths:
        image_path.unlink(missing_ok=True)
