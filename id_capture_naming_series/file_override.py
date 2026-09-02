"""Keep a second reference to a file from re-writing the file.

Frappe keeps one File row per document field that references a file URL:
``frappe.core.doctype.file.utils.attach_files_to_document`` runs on the
``on_update`` of every doctype, walks its Attach and Attach Image fields, and
inserts a File row for any URL that has no row attached to that exact
doctype/name/field yet.

ERPNext Education copies ``Student.image`` onto the linked Customer on every
save (``Student.update_linked_customer``), so saving a Student makes Frappe
insert a second row for the photo this app already stored - and that row
carries a ``file_url`` with no content, so ``File.before_insert`` reads the
image back off disk and saves it again. ``save_file_on_filesystem`` knows
nothing about sub-directories, so the second copy lands flat in
``private/files/<file_name>`` and the new row points there. The folder URL then
still has no row for the Customer, so the next save inserts another one, and
the rows keep piling up.

This override recognises that case - a File that references a URL another row
already owns - and reuses the file that is on disk instead of writing it again.
"""

import os

import frappe
from frappe.core.doctype.file.file import File
from frappe.utils import get_files_path


class ManagedFile(File):
    """File, minus the habit of re-saving a file that is already stored."""

    def before_insert(self):
        owner = self._blob_owner()
        if owner:
            # Recent Frappe takes this flag as "the file is already there".
            self.flags.copy_from_existing_file = True
            self.content_hash = owner.content_hash
            self.file_size = owner.file_size

        super().before_insert()

        if owner and self.file_url != owner.file_url:
            # An older Frappe re-saved it anyway, flat. Put the row back on the
            # file we already have and clear up the copy it just wrote.
            _discard_rewritten_copy(self.file_url)
            self.file_url = owner.file_url
            self.file_name = owner.file_name
            self.content_hash = owner.content_hash
            self.file_size = owner.file_size
            # The file on disk is not ours to delete if this insert rolls back.
            self.flags.pop("new_file", None)

    def _blob_owner(self):
        """The File row that already points at this URL, or ``None``."""
        if self.is_folder or not self.file_url or self.get("content"):
            return None
        if self.is_remote_file:
            return None
        return frappe.db.get_value(
            "File",
            {"file_url": self.file_url, "is_folder": 0},
            ["name", "file_url", "file_name", "content_hash", "file_size"],
            as_dict=True,
        )


def _discard_rewritten_copy(file_url):
    """Delete the copy Frappe just wrote, as long as no row points at it."""
    if not file_url or not file_url.startswith(("/files/", "/private/files/")):
        return
    if frappe.db.count("File", {"file_url": file_url}):
        # A row legitimately references that file - leave it alone.
        return

    is_private = file_url.startswith("/private/files/")
    tail = file_url.split("/files/", 1)[1]
    base = os.path.realpath(get_files_path(is_private=is_private))
    path = os.path.realpath(os.path.join(base, *tail.split("/")))
    if path.startswith(base + os.sep) and os.path.isfile(path):
        os.remove(path)
