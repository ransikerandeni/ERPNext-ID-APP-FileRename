app_name = "id_capture_naming_series"
app_title = "ID Capture Naming Series"
app_publisher = "Ransike Randeni"
app_description = "Folder-aware file uploads for the ID Capture desktop app"
app_email = "25473775+ransikerandeni@users.noreply.github.com"
app_license = "mit"

# This app adds no DocTypes, pages or scheduled jobs. Its whole surface is the
# whitelisted method in api.py, which the desktop app calls as
# id_capture_naming_series.api.upload_to_folder

# Frappe inserts a File row for every document field that references a file
# URL, and each of those rows re-saves the file - flat, outside the folder this
# app wrote it to. ManagedFile makes such a row reuse the existing file instead.
# See file_override.py.
override_doctype_class = {
    "File": "id_capture_naming_series.file_override.ManagedFile",
}
