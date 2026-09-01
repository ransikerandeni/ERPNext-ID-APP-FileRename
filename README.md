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
   `public/files/…` when the upload is not private — creating the folder on
   first use.
4. Creates the matching **File** record, and a File-tree folder of the same name
   under `Home/Attachments`, so ERPNext's file browser mirrors the disk.
5. Sets the document's field to the new file URL.

It returns the file's `name`, `file_name`, `file_url`, `is_private`, `folder`
and the site-relative `path` it was written to.

Re-uploading the same name overwrites the file and updates the existing File
record rather than piling up `-1`, `-2` copies — deliberate, because the name is
derived from the document (index number), so a re-capture replaces the previous
image. Pass `overwrite=0` to keep both.

If registering the File fails, the bytes just written are removed again, so a
failed upload never leaves an orphan on disk.

## Uninstall

```bash
bench --site example-site uninstall-app id_capture_naming_series
```

Files already written stay where they are; the desktop app falls back to
`upload_file` for new uploads.

## License

MIT
