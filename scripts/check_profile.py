"""Check the profile presentation with the pinned, shared Portfolio link parser."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import importlib.util
import os
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".portfolio-checks/scripts/check-presentation.py"
DOCUMENTS = ("README.md", "SYNC.md", "CONTRIBUTING.md")
REPOSITORY = "https://github.com/MirceaStefanescu/MirceaStefanescu"
HOSTS = {"github.com", "raw.githubusercontent.com", "docs.github.com",
         "mirceastefanescu.github.io", "stefanescumircea1990.wordpress.com"}


def load_checker():
    """Load the immutable helper checkout; never fetch or execute a moving branch."""
    if not SHARED.is_file():
        raise ValueError("Missing pinned Portfolio helper; follow CONTRIBUTING.md")
    spec = importlib.util.spec_from_file_location("portfolio_presentation", SHARED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EXTERNAL_HOSTS = set(HOSTS)
    return module


def local_target(root, source, link):
    """Resolve local links and this repository's main URLs against the tested files."""
    link = unescape(link)
    parts = urlsplit(link)
    for suffix in ("/blob/main/", "/tree/main/"):
        if link.startswith(REPOSITORY + suffix):
            return root / unquote(parts.path.split("/main/", 1)[1]), unquote(parts.fragment)
    if link.split("#", 1)[0].rstrip("/") == REPOSITORY:
        return root / "README.md", unquote(parts.fragment)
    if parts.scheme or parts.netloc:
        return None, ""
    if parts.path.startswith("/"):
        raise ValueError("Absolute local path is not a profile asset")
    return (source.parent / unquote(parts.path) if parts.path else source), unquote(parts.fragment)


def check(root, external=False, helper=None):
    """Report blocking local/confirmed remote errors separately from network warnings."""
    helper = helper or load_checker()
    errors, warnings, urls = [], [], set()
    references = 0
    for filename in DOCUMENTS:
        source = root / filename
        try:
            links, _ = helper.parse_document(source)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append(f"{filename}: {error}")
            continue
        for link in links:
            references += 1
            try:
                parts = urlsplit(unescape(link))
                if parts.scheme in {"mailto", "tel"}:
                    continue
                target, fragment = local_target(root, source, link)
                if target is not None:
                    target = target.resolve()
                    if not target.is_relative_to(root.resolve()):
                        raise ValueError("Link escapes the repository")
                    if not target.exists():
                        raise ValueError("Target does not exist")
                    if fragment:
                        target = target / "README.md" if target.is_dir() else target
                        if target.suffix in {".md", ".html"} and fragment not in helper.parse_document(target)[1]:
                            raise ValueError(f"Missing anchor #{fragment}")
                elif parts.scheme == "https":
                    urls.add(urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, "")))
                else:
                    raise ValueError("Unsupported or insecure link scheme")
            except (ValueError, OSError) as error:
                errors.append(f"{filename}: {link}: {error}")
    if external:
        ordered = sorted(urls)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for url, (state, detail) in zip(ordered, pool.map(helper.external_status, ordered)):
                if state == "error":
                    errors.append(f"{url}: {detail}")
                elif state == "warning":
                    warnings.append(f"{url}: {detail}")
    return references, len(urls), errors, warnings


def main():
    """Run offline by default and write a concise GitHub Actions summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true")
    args = parser.parse_args()
    count, urls, errors, warnings = check(ROOT, args.external)
    for error in errors:
        print("ERROR: " + error)
    for warning in warnings:
        print("WARNING: " + warning)
    summary = f"Profile: {count} references, {urls} unique external URLs, {len(errors)} errors, {len(warnings)} warnings."
    print(summary)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("### Profile presentation\n\n" + summary + "\n")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
