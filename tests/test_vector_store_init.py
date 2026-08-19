import unittest
from unittest.mock import patch
from components.vector_store import VectorStore
from config import Config


class FakeChromaRestClient:
    """Fake ChromaRestClient for testing VectorStore initialization failure."""
    def __init__(self, host=None, port=None, **kwargs):
        self.host = host
        self.port = port

    def get_or_create_collection(self, *args, **kwargs):
        raise RuntimeError("Failed to get or create collection from Chroma")


class TestVectorStoreInit(unittest.TestCase):
    @patch("components.vector_store.ChromaRestClient", FakeChromaRestClient)
    @patch.object(Config, "CHROMA_MODE", "rest")
    @patch.object(Config, "USE_CHROMA_SERVER", True)
    def test_vector_store_init_raises_connection_error_on_rest_failure(self):
        with self.assertRaises(ConnectionError) as context:
            with patch("builtins.print"):
                VectorStore()

        err = context.exception
        # Assert that the cause is preserved as RuntimeError
        self.assertIsInstance(err.__cause__, RuntimeError)
        self.assertEqual(str(err.__cause__), "Failed to get or create collection from Chroma")

        # Assert actionable message includes configured host, port, and start_services.ps1
        err_msg = str(err)
        self.assertIn(str(Config.CHROMA_SERVER_HOST), err_msg)
        self.assertIn(str(Config.CHROMA_SERVER_PORT), err_msg)
        self.assertIn("start_services.ps1", err_msg)


if __name__ == "__main__":
    unittest.main()
