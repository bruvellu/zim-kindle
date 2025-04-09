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
        self.bibdata = None
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

        self.bibdata = KindleClippings(self.clippings_file)
        if not self.bibdata.books:
            logger.error("Kindle: No entries found in clippings file")
            return

        # Update root page and import entries
        self.update_root()
        self.import_entries()

        logger.info(
            f"Kindle: Imported {len(self.bibdata.books)} books with {self.bibdata.total_entries} entries"
        )

    def get_page_title(self, page, title):
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

    def get_content_tree(self, content):
        """Convert page content list back to tree."""
        # Convert list to text and parse to regenerate content tree
        if isinstance(content, list):
            text = "".join(content)
        else:
            text = content
        tree = self.format.Parser().parse(text)
        return tree

    def update_root(self):
        """Update root page with Kindle clippings information."""
        # Get content list with the rootpage's title
        page = self.pageview.notebook.get_page(self.rootpage)
        content = self.get_page_title(page, "Kindle Clippings")

        # Add library statistics with a link to the clippings file
        content.extend(
            [
                "\n===== Library =====\n",
                f"* [[file://{self.bibdata.clippings_path}|{self.bibdata.clippings_name}]] | "
                f"{len(self.bibdata.books)} books | "
                f"{self.bibdata.total_entries} entries | "
                f"Updated {self.bibdata.updated}\n",
            ]
        )

        # Add book listing section
        content.append("\n===== Books =====\n")

        # Generate alphabetically sorted book list with links
        sorted_books = sorted(self.bibdata.books.items(), key=lambda x: x[0].lower())
        for title, book in sorted_books:
            # Create valid page name and link
            name = self.rootpage.name + ":" + title
            valid_name = Path.makeValidPageName(name)
            content.append(f"* [[{valid_name}|{book['title']}]]\n")

        # Update content tree and save page
        page.set_parsetree(self.get_content_tree(content))
        self.pageview.notebook.store_page(page)
        logger.debug(f"Kindle: Generated index on {self.rootpage}")

    def import_entries(self):
        """Import Kindle clippings as individual book pages."""
        for book in self.bibdata.books.values():
            # Create valid page name using Zim's validation method
            name = self.rootpage.name + ":" + book["title"]
            path = Path(Path.makeValidPageName(name))

            page = self.pageview.notebook.get_page(path)
            content = self.get_page_title(page, book["title"])

            if book["author"]:
                content.append(f"\n**Author:** {book['author']}\n\n")
            else:
                content.append("\n")

            for entry in book["entries"]:
                content.append(
                    f"{entry['date'].strftime('%Y-%m-%d %H:%M')} | "
                    f"**{entry['type'].title()}** | "
                    f"Page: {entry.get('page', 'N/A')} | "
                    f"Location: {entry.get('location', 'N/A')}\n"
                    f"{entry['text']}\n\n"
                )

            # Update content tree and save page
            page.set_parsetree(self.get_content_tree(content))
            self.pageview.notebook.store_page(page)
            logger.debug(f"Kindle: Imported book {book['title']}")


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

            # Make sure titles have no colon (reserved for namespaces)
            title = book_info["title"].replace(":", " -")
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
        # Look for the last parenthetical expression as the author
        last_paren_match = re.search(r"\(([^()]+)\)$", line)

        if last_paren_match:
            author = last_paren_match.group(1).strip()
            # Extract title (everything before the last parentheses)
            title = line[: last_paren_match.start()].strip()
            return {"title": title, "author": author}

        # If no parentheses, assume the whole line is the title
        return {"title": line, "author": None}

    def _parse_metadata(self, line):
        """Parse the metadata line for type, page, location, and date."""
        # Extract the entry type (highlight, note, etc)
        type_match = re.search(r"- Your (?P<type>\w+)", line)
        entry_type = type_match.group("type").lower() if type_match else "unknown"

        # Extract page information - improved pattern
        page_match = re.search(r"on page (?P<page>\d+(-\d+)?)", line)
        page = page_match.group("page") if page_match else None

        # Extract location information - improved pattern
        location_match = re.search(r"Location (?P<location>\d+(-\d+)?)", line)
        location = location_match.group("location") if location_match else None

        # Extract date information
        date_match = re.search(r"Added on (?P<date>.+?)(\||$)", line)
        date_str = (
            date_match.group("date").strip().replace(",", "") if date_match else ""
        )

        try:
            # Try different date formats to accommodate various Kindle date styles
            date = datetime.strptime(date_str, "%A %B %d %Y %I:%M:%S %p")
        except ValueError:
            try:
                date = datetime.strptime(date_str, "%A %B %d %Y %H:%M:%S")
            except ValueError:
                try:
                    date = datetime.strptime(date_str, "%A %d %B %Y %I:%M:%S %p")
                except ValueError:
                    try:
                        date = datetime.strptime(date_str, "%A %d %B %Y %H:%M:%S")
                    except ValueError:
                        date = datetime.now()

        return {"type": entry_type, "page": page, "location": location, "date": date}

    def generate_folders(self):
        """Generate folders based on the first letter of book titles."""
        folders = {title[0].upper() for title in self.books.keys() if title}
        return sorted(folders)
