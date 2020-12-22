"""
Commands for observe web app.
"""
import os

import azcam_observe.webobs  # load webob object
from flask import Blueprint, render_template, request
from werkzeug.utils import secure_filename

import azcam

observe = Blueprint(
    "webobs",
    __name__,
    static_folder="static_webobs",
    template_folder="",
)


@observe.route("/observe/upload", methods=["POST"])
def webobs_upload():
    url = request.url
    print(url)
    azcam.log(url, prefix="Web-> ")
    f = request.files["file"]
    f.save(os.path.join(azcam.db.webserver.config["UPLOAD_FOLDER"], secure_filename(f.filename)))
    return "OK"


@observe.route("/observe", defaults={"page": "observe"}, methods=["GET"])
def show_webobs(page):
    table_data = [
        list(range(17)),
    ]
    return render_template(f"{page}.html", table_data=table_data)


def load():
    if azcam.db.get("webserver") is not None:
        azcam.db.webserver.app.register_blueprint(observe)

    azcam.log("Loaded azcam_observe")
