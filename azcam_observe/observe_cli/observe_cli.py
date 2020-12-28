"""
Observe class.

Notes:
IPython config needs:
 c.InteractiveShellApp.gui = 'qt'
 c.InteractiveShellApp.pylab = 'qt'
"""

import time

import azcam
from azcam_observe.observe_common import ObserveCommon


class ObserveCli(ObserveCommon):
    """
    The Observe class which implements observing scripts.

    This class is instantiated as the *observe* object.
    Scripts are run using observe.observe().
    """

    def __init__(self):

        super().__init__()

        # add object to api and cli_cmds
        setattr(azcam.api, "observe", self)

    def initialize(self):
        """
        Initialize observe.
        """

        # set defaults from parfile
        self.script_file = azcam.api.config.get_script_par(
            "observe", "script_file", "default", "", "observing_script.txt"
        )
        number_cycles = azcam.api.config.get_script_par(
            "observe", "number_cycles", "default", "", 1
        )
        self.number_cycles = int(number_cycles)

        # define column order
        self.column_order = [
            "cmdnumber",
            "status",
            "command",
            "argument",
            "exptime",
            "type",
            "title",
            "numexp",
            "filter",
            "ra",
            "dec",
            "epoch",
            "expose_flag",
            "movetel_flag",
            "steptel_flag",
            "movefilter_flag",
            "movefocus_flag",
        ]

        self.column_number = {}
        for i, x in enumerate(self.column_order):
            self.column_number[i] = x

        return

    def observe(self, script_file="prompt", number_cycles=1):
        """
        Execute a complete observing script.
        This code assumes that the filename, timing code, and binning have all been previously set.
        Creates a .out file with a status integer in front of commands executed.

        :param script_file: full path name of script file.
        :param number_cycles: Number of times to run the script.
        :return: None
        """

        # get inputs
        if script_file == "prompt":
            script_file = azcam.api.config.get_script_par(
                "observe", "script_file", "default", "Enter script file name", ""
            )
            script_file = azcam.utils.file_browser(
                script_file, [("script files", ("*.txt"))], Label="Select script file"
            )
            if script_file is not None and script_file != "":
                script_file = script_file[0]
                self.script_file = script_file
                azcam.api.config.set_script_par("observe", "script_file", script_file)
            else:
                return "ERROR selecting script file"

        if number_cycles == "prompt":
            self.number_cycles = azcam.api.config.get_script_par(
                "observe",
                "number_cycles",
                "prompt",
                "Enter number of cycles to run script",
                number_cycles,
            )
        else:
            self.number_cycles = number_cycles  # use value specified
        self.number_cycles = int(self.number_cycles)
        azcam.api.config.set_script_par("observe", "number_cycles", self.number_cycles)

        # read and parse the script
        self.read_file(script_file)
        self.parse()

        # execute the commands
        self.run()

        return
