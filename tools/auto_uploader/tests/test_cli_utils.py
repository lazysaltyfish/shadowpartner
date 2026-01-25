import tempfile
import unittest

from tools.auto_uploader import cli


class TestCliUtils(unittest.TestCase):
    def test_extract_youtube_id_variants(self):
        self.assertEqual(cli.extract_youtube_id("6LJ_ny-kmww"), "6LJ_ny-kmww")
        self.assertEqual(
            cli.extract_youtube_id("https://www.youtube.com/watch?v=6LJ_ny-kmww"),
            "6LJ_ny-kmww",
        )
        self.assertEqual(
            cli.extract_youtube_id("https://youtu.be/6LJ_ny-kmww?t=1"),
            "6LJ_ny-kmww",
        )
        self.assertEqual(
            cli.extract_youtube_id("https://www.youtube.com/shorts/6LJ_ny-kmww"),
            "6LJ_ny-kmww",
        )

    def test_normalize_youtube_url(self):
        self.assertEqual(
            cli.normalize_youtube_url("https://youtu.be/6LJ_ny-kmww"),
            "https://www.youtube.com/watch?v=6LJ_ny-kmww",
        )

    def test_extract_playlist_id(self):
        url = "https://www.youtube.com/watch?v=6LJ_ny-kmww&list=PL123ABC"
        self.assertEqual(cli.extract_playlist_id(url), "PL123ABC")

    def test_normalize_playlist_url(self):
        url = "https://www.youtube.com/watch?v=6LJ_ny-kmww&list=PL123ABC"
        self.assertEqual(cli.normalize_playlist_url(url), "https://www.youtube.com/playlist?list=PL123ABC")

    def test_read_url_list(self):
        content = "\n".join(
            [
                "# comment",
                "https://youtu.be/6LJ_ny-kmww",
                "https://youtu.be/6LJ_ny-kmww # inline comment",
                "",
                "; another comment",
                "// comment style",
            ]
        )
        with tempfile.NamedTemporaryFile("w+", delete=True) as handle:
            handle.write(content)
            handle.flush()
            urls = cli.read_url_list(handle.name)
        self.assertEqual(
            urls,
            [
                "https://youtu.be/6LJ_ny-kmww",
                "https://youtu.be/6LJ_ny-kmww",
            ],
        )


if __name__ == "__main__":
    unittest.main()
