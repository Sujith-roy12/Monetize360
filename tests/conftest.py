import os
import tempfile
from pathlib import Path

_temp = tempfile.TemporaryDirectory(prefix="monetize-v2-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_temp.name) / "tests.db")
os.environ["ADMIN_TOKEN"] = "test-publisher"
os.environ["EDITOR_TOKEN"] = "test-editor"
os.environ["GEMINI_API_KEY"] = ""
