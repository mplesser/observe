"""
Webobs commands for observe web app.
"""

import datetime
import os
import time
import urllib

import azcam
import azcam.server
from azcam_observe.observe_common import ObserveCommon


class WebObs(ObserveCommon):
    """
    API interface for server application.
    """

    def __init__(self):

        super().__init__()

        self.message = ""

        # add object to api and cli_cmds
        setattr(azcam.api, "webobs", self)
        azcam.db.cli_cmds["webobs"] = self

    def watchdog(self):
        """
        Update timestamp indicating GUI in running and highlight current table row.
        """

        precision = 0

        dateTimeObj = datetime.datetime.now()
        timestamp = str(dateTimeObj)

        if precision >= 6:
            pass
        elif precision == 0:
            timestamp = timestamp[:-7]
        else:
            tosecs = timestamp[:-7]
            frac = str(round(float(timestamp[-7:]), precision))
            timestamp = tosecs + frac

        # check abort
        if self._abort_gui:
            self.status("Aborting GUI")
            print("Aborting observe GUI")
            return

        if self._paused:
            self.status("Script PAUSED")

        # highlights
        if self._do_highlight:
            row = self.current_line  # no race condition
            if row != -1:
                if self._paused:
                    self.highlight_row(row, 2)
                elif self._abort_script:
                    self.highlight_row(row, 3)
                else:
                    self.highlight_row(row, 1)
                # clear previous row
                if row > 0:
                    self.highlight_row(row - 1, 0)
            self._do_highlight = 0

        # print(f"watchdog on line {self.current_line}")
        data = {
            "timestamp": timestamp,
            "currentrow": self.current_line,
            "message": self.message,
        }

        return data

    def load_script(self, scriptname):
        """
        Load script into table.
        """

        scriptname = urllib.parse.unquote(scriptname)
        scriptfile = os.path.join(
            azcam.db.webserver.app.config["upload_folder"], os.path.basename(scriptname)
        )
        scriptfile = os.path.normpath(scriptfile)

        self.read_file(scriptfile)
        self.parse()

        table_list = []
        for row in self.commands:
            l1 = list(row.values())
            table_list.append(l1[1:-3])  # ignore some cols

        return table_list
