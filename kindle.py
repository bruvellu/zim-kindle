# kindle.py - Zim plugin for importing Kindle clippings
# Based on zim-bibtex plugin structure and _kindle-to-zim.py parser

import re
import os
from datetime import datetime

import logging

logger = logging.getLogger("zim.plugins.kindle")

from zim.actions import action
from zim.formats import get_format
from zim.gui.pageview import PageViewExtension
from zim.notebook import Path
from zim.plugins import PluginClass


class KindlePlugin(PluginClass):
    plugin_info = {
        "name": _("Kindle Clippings"),  # T: plugin name
        "description": _(
            "Import Kindle highlights and notes into Zim pages"
        ),  # T: plugin description
        "author": "Your Name",
        "help": "Plugins:Kindle",
    }

    plugin_preferences = ()

    plugin_notebook_properties = (
        (
            "rootpage",
            "namespace",
            _("Root page for clippings"),
            Path(":Kindle"),
        ),  # T: preference option
        (
            "clippings_file",
            "file",
            _("Path to 'My Clippings.txt'"),
            "",
        ),  # T: preference option
    )


class KindlePageViewExtension(PageViewExtension):
    def __init__(self, plugin, pageview):
        PageViewExtension.__init__(self, plugin, pageview)
        self.properties = None
        self.rootpage = None
        self.clippings_file = None
        self.format = get_format("wiki")
        self._update_properties()

    def _update_properties(self):
        self.properties = self.plugin.notebook_properties(self.pageview.notebook)
        self.rootpage = self.properties["rootpage"]
        self.clippings_file = self.properties["clippings_file"]

    @action(_("Import _Kindle Clippings"), menuhints="tools")  # T: menu item
    def import_kindle_clippings(self):
        self._update_properties()
        if not self.clippings_file:
            logger.error("Kindle: No clippings file specified in notebook properties")
            return

        clippings = KindleClippings(self.clippings_file)
        if not clippings.books:
            logger.error("Kindle: No entries found in clippings file")
            return

        # Create root page
        root = self.pageview.notebook.get_page(self.rootpage)
        content = self._get_page_content(root, "Kindle Clippings")
        content += self._get_stats_content(clippings)
        root.set_parsetree(self._parse_to_tree(content))
        self.pageview.notebook.store_page(root)

        # Create book pages
        for book in clippings.books.values():
            path = Path(self.rootpage.name + ":" + sanitize_pagename(book["title"]))
            page = self.pageview.notebook.get_page(path)
            content = self._format_book_page(book)
            page.set_parsetree(self._parse_to_tree(content))
            self.pageview.notebook.store_page(page)

        logger.info(
            f"Imported {len(clippings.books)} books with {clippings.total_entries} entries"
        )

    def _get_page_content(self, page, title):
        """Get or create basic page content with title."""
        if page.hascontent:
            # Get content tree and dump as a list
            page_tree = page.get_parsetree()
            page_content = self.format.Dumper().dump(page_tree)
            # Only keep title and creation date
            page_content = page_content[:2]
        else:
            # Generate content list with new title
            page_content = [
                f"====== {title} ======\n",
                f"Created {datetime.now().strftime('%A %d %B %Y')}\n",
            ]
        return page_content

    def _get_stats_content(self, clippings):
        """Generate statistics section for the root page."""
        stats = [
            "\n===== Library =====\n",
            f"* {clippings.clippings_name} | "
            f"{len(clippings.books)} books | "
            f"{clippings.total_entries} entries | "
            f"Updated {clippings.updated}\n",
        ]

        if clippings.folders:
            stats.extend(
                [
                    "\n===== Folders =====\n",
                    "* "
                    + " | ".join(
                        [f"[[+{folder}|{folder}]]" for folder in clippings.folders]
                    )
                    + "\n",
                ]
            )

        return stats

    def _format_book_page(self, book):
        """Format a book page with all its entries."""
        content = [
            f"====== {book['title']} ======\n",
            f"Created {datetime.now().strftime('%A %d %B %Y')}\n\n",
        ]

        if book["author"]:
            content.append(f"**Author:** {book['author']}\n\n")

        for entry in book["entries"]:
            content.append(
                f"**{entry['type'].title()}** - {entry['date'].strftime('%Y-%m-%d %H:%M')}\n"
                f"Page: {entry.get('page', 'N/A')} | Location: {entry.get('location', 'N/A')}\n"
                f"{entry['text']}\n\n"
            )
        return "".join(content)

    def _parse_to_tree(self, content):
        """Convert page content to a parse tree."""
        if isinstance(content, list):
            content = "".join(content)
        return self.format.Parser().parse(content)


class KindleClippings:
    def __init__(self, filepath):
        self.clippings_file = filepath
        self.clippings_path = os.path.expanduser(filepath)
        self.clippings_name = os.path.basename(self.clippings_path)
        self.books = {}
        self.total_entries = 0
        self.folders = []
        self.updated = datetime.now().astimezone().replace(microsecond=0).isoformat()

        try:
            logger.debug(
                f"Kindle: Importing {self.clippings_path}... (this might take a while)"
            )
            with open(self.clippings_path, "r", encoding="utf-8-sig") as f:
                raw_entries = f.read().split("==========\n")
                self.parse_entries(raw_entries)

            # Generate statistics
            self.total_entries = sum(
                len(book["entries"]) for book in self.books.values()
            )
            self.folders = self.generate_folders()
            logger.debug(
                f"Kindle: Loaded {self.total_entries} entries from {len(self.books)} books in {self.clippings_name}"
            )
        except Exception as e:
            logger.error(f"Kindle: Error reading clippings file: {e}")
            self.books = {}
            self.total_entries = 0
            self.folders = []

    def parse_entries(self, raw_entries):
        """Parse the raw entries from the clippings file."""
        for entry in raw_entries:
            if not entry.strip():
                continue

            lines = [l.strip() for l in entry.split("\n") if l.strip()]
            if len(lines) < 3:
                continue

            meta = self._parse_metadata(lines[1])
            if not meta:
                continue

            book_info = self._parse_title_author(lines[0])
            text = "\n".join(lines[2:]) if len(lines) > 2 else ""

            title = book_info["title"]
            if title not in self.books:
                self.books[title] = {
                    "title": title,
                    "author": book_info.get("author"),
                    "entries": [],
                    "updated": self.updated,
                }

            self.books[title]["entries"].append(
                {
                    "type": meta["type"],
                    "page": meta.get("page"),
                    "location": meta.get("location"),
                    "date": meta["date"],
                    "text": text,
                }
            )

    def _parse_title_author(self, line):
        """Parse the title and author from the first line."""
        match = re.match(r"^(?P<title>.+?)(\s+\((?P<author>.+)\))?$", line)
        if match:
            return {
                "title": match.group("title").strip(),
                "author": match.group("author"),
            }
        return {"title": line, "author": None}

    def _parse_metadata(self, line):
        """Parse the metadata line for type, page, location, and date."""
        patterns = [
            r"- Your (?P<type>Highlight|Note|Bookmark).*?(?:page (?P<page>\d+))?.*?(?:Location (?P<location>[\d-]+))?.*?Added on (?P<date>.+)",
            r"- Your (?P<type>\w+).*?\| Added on (?P<date>.+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                date_str = match.group("date").replace(",", "")
                try:
                    date = datetime.strptime(date_str, "%A %d %B %Y %I:%M:%S %p")
                except ValueError:
                    try:
                        date = datetime.strptime(date_str, "%A %d %B %Y %H:%M:%S")
                    except ValueError:
                        date = datetime.now()

                return {
                    "type": match.group("type").lower(),
                    "page": match.group("page")
                    if match.groupdict().get("page")
                    else None,
                    "location": match.group("location")
                    if match.groupdict().get("location")
                    else None,
                    "date": date,
                }
        return None

    def generate_folders(self):
        """Generate folders based on the first letter of book titles."""
        folders = {title[0].upper() for title in self.books.keys() if title}
        return sorted(folders)


def sanitize_pagename(name):
    return re.sub(r"[^a-zA-Z0-9_:.-]", "_", name)
