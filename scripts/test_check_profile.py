"""Regression coverage for profile-specific local and remote link routing."""
from pathlib import Path
import tempfile
import unittest
from check_profile import check, load_checker, local_target, REPOSITORY


class ProfileTests(unittest.TestCase):
    """Check the profile's boundaries while reusing the shared parser regression suite."""
    def setUp(self):
        """Create presentation fixtures without touching a working repository."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.helper = load_checker()
        for name in ("README.md", "SYNC.md", "CONTRIBUTING.md"):
            (self.root / name).write_text("# Profile\n", encoding="utf-8")

    def test_own_repository_links_use_the_tested_checkout(self):
        """Validate new local anchors without consulting the published main branch."""
        (self.root / "README.md").write_text(
            "# Profile\n[Guide](" + REPOSITORY + "/blob/main/SYNC.md#profile)\n", encoding="utf-8")
        self.assertEqual(check(self.root, helper=self.helper)[2], [])
        (self.root / "SYNC.md").write_text("# Different\n", encoding="utf-8")
        self.assertTrue(any("Missing anchor" in e for e in check(self.root, helper=self.helper)[2]))

    def test_missing_escaping_and_symlink_targets_fail(self):
        """Reject traversal and symlinks even if the external file exists."""
        outside = self.root.parent / (self.root.name + "-outside.md")
        outside.write_text("# Outside\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.root / "escape.md").symlink_to(outside)
        for destination in ("missing.png", "../" + outside.name, "escape.md"):
            (self.root / "README.md").write_text("[Link](" + destination + ")\n", encoding="utf-8")
            with self.subTest(destination=destination):
                self.assertTrue(check(self.root, helper=self.helper)[2])

    def test_portfolio_images_and_pages_remain_remote(self):
        """Do not accidentally resolve another repository's files inside this checkout."""
        for url in ("https://raw.githubusercontent.com/MirceaStefanescu/Portfolio/main/image.png",
                    "https://mirceastefanescu.github.io/Portfolio/",
                    "https://github.com/MirceaStefanescu/Portfolio/blob/main/README.md"):
            self.assertEqual(local_target(self.root, self.root / "README.md", url), (None, ""))

    def test_network_outcomes_remain_distinct(self):
        """Confirmed broken destinations fail; transient outcomes remain warnings."""
        (self.root / "README.md").write_text("[Site](https://github.com/example)\n", encoding="utf-8")
        self.helper.external_status = lambda _: ("warning", "HTTP 429")
        self.assertEqual(check(self.root, True, self.helper)[2], [])
        self.assertEqual(len(check(self.root, True, self.helper)[3]), 1)
        self.helper.external_status = lambda _: ("error", "HTTP 404 confirmed twice")
        self.assertEqual(len(check(self.root, True, self.helper)[2]), 1)

    def test_insecure_or_executable_schemes_fail(self):
        """A profile link cannot introduce cleartext or script destinations."""
        for url in ("http://github.com/example", "javascript:alert"):
            (self.root / "README.md").write_text("[Link](" + url + ")\n", encoding="utf-8")
            with self.subTest(url=url):
                self.assertTrue(check(self.root, helper=self.helper)[2])


if __name__ == "__main__":
    unittest.main()
