"""Whitelisted upload endpoint for the ID Capture desktop app.

Frappe's stock ``upload_file`` writes every attachment flat into
``sites/<site>/private/files``: it strips path separators out of file names, so
no API client can place a file in a sub-directory. This method does what the
desktop app needs instead - write the file into
``private/files/<folder>/<file_name>``, creating the folder on first use, then
register it as a File and link it to the document field.

This module is the whole of the ``id_capture_naming_series`` Frappe app; the
desktop app calls it as ``id_capture_naming_series.api.upload_to_folder``. See
the app's README for how to install it on a site.
"""

import hashlib
import os
import re

import frappe
from frappe import _
from frappe.utils import cint, get_files_path

# A folder or file name is one path segment - no separators, no traversal.
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")

DEFAULT_MAX_FILE_SIZE = 25 * 1024 * 1024


@frappe.whitelist()
def upload_to_folder(
    folder=None,
    file_name=None,
    doctype=None,
    docname=None,
    fieldname=None,
    is_private=1,
    overwrite=1,
):
    """Store the posted file at ``<private|public>/files/<folder>/<file_name>``.

    Returns the same shape as Frappe's ``upload_file`` so the caller can treat
    both paths alike.
    """
    uploaded = (frappe.request.files or {}).get("file")
    if uploaded is None:
        frappe.throw(_("No file was received"), title=_("Upload failed"))

    is_private = cint(is_private)
    overwrite = cint(overwrite)
    file_name = _clean_segment(file_name or uploaded.filename, _("file name"))
    folder = _clean_segment(folder, _("folder name")) if folder else ""

    content = uploaded.stream.read()
    max_size = frappe.conf.get("max_file_size") or DEFAULT_MAX_FILE_SIZE
    if len(content) > max_size:
        frappe.throw(
            _("File is larger than the maximum allowed size of {0} bytes").format(max_size),
            exc=frappe.exceptions.ValidationError,
        )

    _check_permission(doctype, docname)

    full_path, file_url, rel_path = _target_path(folder, file_name, is_private)
    if os.path.exists(full_path) and not overwrite:
        full_path, file_url, rel_path = _unique_path(full_path, file_url, rel_path)

    _ensure_directory(os.path.dirname(full_path))
    with open(full_path, "wb") as f:
        f.write(content)

    try:
        folder_record = _folder_record(folder) if folder else None
        file_doc = _register_file(
            file_name, file_url, is_private, folder_record,
            doctype, docname, fieldname, content,
        )
    except Exception:
        # Never leave a file on disk that nothing in the site points at.
        if os.path.exists(full_path):
            os.remove(full_path)
        raise

    if doctype and docname and fieldname:
        frappe.db.set_value(doctype, docname, fieldname, file_url)

    return {
        "name": file_doc.name,
        "file_name": file_name,
        "file_url": file_url,
        "is_private": is_private,
        "folder": folder_record or "",
        "path": rel_path,
    }


def _ensure_directory(path):
    """Use the folder that is already there, and create it only when missing."""
    if os.path.isdir(path):
        return
    if os.path.exists(path):
        frappe.throw(
            _("Cannot use {0} as a folder: a file of that name is already there").format(path),
            exc=frappe.exceptions.ValidationError,
        )
    # exist_ok covers two uploads for the same person arriving at once.
    os.makedirs(path, exist_ok=True)


def _clean_segment(value, label):
    value = (value or "").strip()
    if not value or value in (".", "..") or not SAFE_SEGMENT.match(value):
        frappe.throw(
            _("Invalid {0}: {1}").format(label, value or _("(empty)")),
            exc=frappe.exceptions.ValidationError,
        )
    return value


def _check_permission(doctype, docname):
    """Only let through someone who could attach the file the normal way."""
    if doctype and docname:
        if not frappe.has_permission(doctype, "write", doc=docname):
            raise frappe.PermissionError(
                _("Not permitted to attach files to {0} {1}").format(doctype, docname)
            )
    elif not frappe.has_permission("File", "create"):
        raise frappe.PermissionError(_("Not permitted to create files"))


def _target_path(folder, file_name, is_private):
    base = os.path.realpath(get_files_path(is_private=is_private))
    parts = [base, folder, file_name] if folder else [base, file_name]
    full_path = os.path.realpath(os.path.join(*parts))
    if not full_path.startswith(base + os.sep):
        frappe.throw(_("Refusing to write outside the site's files folder"))

    # Public files are served from /files but live in public/files on disk.
    url_root = "/private/files" if is_private else "/files"
    disk_root = "private/files" if is_private else "public/files"
    tail = f"{folder}/{file_name}" if folder else file_name
    return full_path, f"{url_root}/{tail}", f"{disk_root}/{tail}"


def _unique_path(full_path, file_url, rel_path):
    """Append -1, -2, ... rather than replacing a file that is already there."""
    stem, ext = os.path.splitext(full_path)
    counter = 1
    while os.path.exists(f"{stem}-{counter}{ext}"):
        counter += 1
    suffix = f"-{counter}"

    def _bump(value):
        head, extension = os.path.splitext(value)
        return f"{head}{suffix}{extension}"

    return f"{stem}{suffix}{ext}", _bump(file_url), _bump(rel_path)


def _register_file(
    file_name, file_url, is_private, folder_record, doctype, docname, fieldname, content
):
    """Create - or refresh - the File record pointing at the written file.

    The record's file_url has to stay exactly the path the file was written to:
    private files are served by looking a File up by that URL, so a record
    pointing anywhere else shows as a broken image on the document.
    """
    content_hash = hashlib.md5(content).hexdigest()

    existing = _existing_record(file_url, doctype, docname, fieldname)
    if existing:
        file_doc = frappe.get_doc("File", existing)
        file_doc.attached_to_doctype = doctype
        file_doc.attached_to_name = docname
        file_doc.attached_to_field = fieldname
        file_doc.file_size = len(content)
        file_doc.content_hash = content_hash
        file_doc.save(ignore_permissions=True)
        return file_doc

    file_doc = frappe.get_doc({
        "doctype": "File",
        "file_name": file_name,
        "file_url": file_url,
        "is_private": is_private,
        "folder": folder_record,
        "attached_to_doctype": doctype,
        "attached_to_name": docname,
        "attached_to_field": fieldname,
        "file_size": len(content),
        "content_hash": content_hash,
    })
    # The bytes are already on disk. Frappe v15 takes this flag as "the blob is
    # already there, leave it alone"; older versions have no such flag and save
    # the content again into a flat path, which _keep_file_url puts right.
    file_doc.flags.copy_from_existing_file = True
    file_doc.insert(ignore_permissions=True)
    _keep_file_url(file_doc, file_name, file_url, len(content), content_hash)
    return file_doc


def _existing_record(file_url, doctype, docname, fieldname):
    """The row for this attachment, if a re-capture is replacing an earlier one.

    Scoped to the document field being attached to. Several rows can share a
    file_url - Frappe adds one per document field that references it, and
    ERPNext copies a Student's photo onto the linked Customer - so an unscoped
    lookup here would re-point another document's attachment at this one.
    """
    filters = {"file_url": file_url, "is_folder": 0}
    if doctype and docname:
        filters["attached_to_doctype"] = doctype
        filters["attached_to_name"] = docname
        filters["attached_to_field"] = fieldname or ("is", "not set")
    else:
        filters["attached_to_doctype"] = ("is", "not set")
    return frappe.db.get_value("File", filters, "name")


def _keep_file_url(file_doc, file_name, file_url, file_size, content_hash):
    """Undo a re-save that moved the record away from the file we wrote.

    Frappe's File writes the content itself on insert and then points the
    record at ``/private/files/<file_name>``, flat. That leaves a second, often
    re-encoded copy of the image outside the folder, and the document's field
    then references a URL no File record matches - a blank image. Put the
    record back on our path and clear up the copy.
    """
    stray_url = file_doc.file_url
    if stray_url == file_url and file_doc.file_name == file_name:
        return

    _remove_stray_copy(file_doc.name, stray_url, file_url)
    frappe.db.set_value(
        "File",
        file_doc.name,
        {
            "file_url": file_url,
            "file_name": file_name,
            "file_size": file_size,
            "content_hash": content_hash,
        },
        update_modified=False,
    )
    file_doc.file_url = file_url
    file_doc.file_name = file_name


def _remove_stray_copy(file_name_doc, stray_url, kept_url):
    """Delete the extra copy Frappe wrote, if nothing else points at it."""
    if not stray_url or stray_url == kept_url:
        return
    if not stray_url.startswith(("/files/", "/private/files/")):
        return
    if frappe.db.count("File", {"file_url": stray_url, "name": ("!=", file_name_doc)}):
        # Another record legitimately references that file - leave it alone.
        return

    is_private = stray_url.startswith("/private/files/")
    tail = stray_url.split("/files/", 1)[1]
    base = os.path.realpath(get_files_path(is_private=is_private))
    path = os.path.realpath(os.path.join(base, *tail.split("/")))
    if path.startswith(base + os.sep) and os.path.isfile(path):
        os.remove(path)


def _folder_record(folder):
    """The File-tree folder of the same name, so the ERPNext UI matches disk.

    An existing folder is always reused - by its path, which is how Frappe names
    folder records, and by a lookup on the name as a fallback. A new one is
    created only when neither finds anything.
    """
    parent = "Home/Attachments"
    name = f"{parent}/{folder}"
    if frappe.db.get_value("File", name, "is_folder"):
        return name

    existing = frappe.db.get_value(
        "File", {"file_name": folder, "is_folder": 1, "folder": parent}, "name"
    )
    if existing:
        return existing

    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": folder,
        "is_folder": 1,
        "folder": parent,
    })
    try:
        doc.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        # Another upload for the same person created it in between.
        return name
    return doc.name
