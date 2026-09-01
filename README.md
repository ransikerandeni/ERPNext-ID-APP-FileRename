# ID Capture Naming Series

A one-method Frappe app that lets the
[ID Capture desktop app](https://github.com/Pamod460/ID-Photo-Capture-App)
save its photos and signatures into **named folders** on the site:

```
frappe-bench/sites/example-site/private/files/200012345678/EDU-STU-IMAGE-26810001.jpg
```

Frappe's built-in `upload_file` API strips path separators out of file names, so
every attachment lands flat in `private/files/`. This app adds a whitelisted
method that writes into a sub-directory instead, registers the File, and links
it to the document field.

The desktop app works without this app installed — it falls back to
`upload_file` and files are stored flat — so installing it is what turns the
folder layout on.

## Install

```bash
cd ~/frappe-bench
bench get-app id_capture_naming_series https://github.com/ransikerandeni/ERPNext-ID-APP-FileRename.git --branch main
bench --site example-site install-app id_capture_naming_series
bench restart
```

The repository is named `ERPNext-ID-APP-FileRename` but the app is
`id_capture_naming_series`. Recent bench versions read the app name out of
`pyproject.toml` and rename the cloned directory themselves, but passing the app
name explicitly as above works on every version and is the safer form.

On a development bench, restart `bench start` instead of `bench restart`.

Works on Frappe v14 and v15 — the endpoint only uses `File`, `get_files_path`
and `has_permission`, which behave the same on both.

The method is then reachable at
`/api/method/id_capture_naming_series.api.upload_to_folder`, which is the path
the desktop app calls by default.

## Upgrading

```bash
cd ~/frappe-bench/apps/id_capture_naming_series
git pull
cd ~/frappe-bench
bench --site example-site migrate
bench restart
```

## What the method does

`upload_to_folder(folder, file_name, doctype, docname, fieldname, is_private=1, overwrite=1)`
takes the posted file and:

1. Validates the folder and file name as a single safe path segment
   (`[A-Za-z0-9][A-Za-z0-9._@-]*`) — no separators, no `..` — and refuses to
   write anywhere outside the site's files directory.
2. Checks the caller has **write** permission on the target document (or
   **create** on File when no document is given), so it grants nothing the
   normal attachment flow would not.
3. Writes the bytes to `private/files/<folder>/<file_name>` — or
   `public/files/…` when the upload is not private.
4. Creates the matching **File** record, and a File-tree folder of the same name
   under `Home/Attachments`, so ERPNext's file browser mirrors the disk.
5. Sets the document's field to the new file URL.

It returns the file's `name`, `file_name`, `file_url`, `is_private`, `folder`
and the site-relative `path` it was written to.

### Folders are reused, never duplicated

A folder is created only when it is not already there. If one named after the
field's value exists — because an earlier photo, the signature for the same
person, or someone working directly on the server created it — that folder is
used as it is, and nothing already in it is touched:

- **On disk**, an existing directory is reused; only a missing one is created.
- **In ERPNext**, the File-tree folder is matched by its path
  (`Home/Attachments/<value>`) and, failing that, by a lookup on its name, so a
  folder created some other way is still found rather than duplicated.
- Two uploads for the same person arriving at once are safe: the directory is
  created with `exist_ok`, and a folder record that loses the race is picked up
  instead of raising.

Matching is exact, so values that differ in case or spacing (`912345678V` and
`912345678v`) are different folders — they are different field values.

If a plain **file** already occupies the folder's path, the upload stops with a
clear message rather than failing halfway.

Re-uploading the same name overwrites the file and updates the existing File
record rather than piling up `-1`, `-2` copies — deliberate, because the name is
derived from the document (index number), so a re-capture replaces the previous
image. Pass `overwrite=0` to keep both.

If registering the File fails, the bytes just written are removed again, so a
failed upload never leaves an orphan on disk.

### Why the File record's URL matters

Frappe serves a private file by looking up a File record whose `file_url` is
exactly the requested path, so the record has to keep pointing at the file in
its folder. Frappe's own File doctype writes the content again on insert and
repoints the record at a flat `/private/files/<name>`, which leaves a second,
re-encoded copy outside the folder and makes the document show a blank image.

The method sets `copy_from_existing_file`, which Frappe v15 takes as "the blob
is already there, leave it alone". Older versions have no such flag, so after
inserting, the record is put back on the folder path and the extra flat copy is
deleted — but only when no other File record references it.

Uploading the same name again reuses the existing File record and refreshes its
size and hash instead of adding a second row for the same path.

## Troubleshooting

**A blank image on the document, and a small unreadable copy in
`private/files/`** — that is this bug, from a version of the app before 0.0.2.
Update the app, delete the stray flat copies, and capture again:

```bash
ls -la ~/frappe-bench/sites/example-site/private/files/*.jpg
```

The healthy image is the one inside the folder named after the field value; the
flat one of the same name can be removed. Any File record still pointing at the
flat copy can be deleted from the File list in the Desk.

## Uninstall

```bash
bench --site example-site uninstall-app id_capture_naming_series
```

Files already written stay where they are; the desktop app falls back to
`upload_file` for new uploads.

## License

MIT
