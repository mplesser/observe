"""
Observe class.

Notes:
IPython config needs:
 c.InteractiveShellApp.gui = 'qt'
 c.InteractiveShellApp.pylab = 'qt'
"""

import os
import sys
import time

from PySide2 import QtGui, QtCore
from PySide2.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QWidget,
    QTableWidgetItem,
    QApplication,
)
from PySide2.QtCore import QTimer, Signal, Slot

import azcam
from .observe_gui_ui import Ui_observe


class GenericWorker(QtCore.QObject):

    start = Signal(str)
    finished = Signal()

    def __init__(self, function, *args, **kwargs):
        super(GenericWorker, self).__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.start.connect(self.run)

    @Slot()
    def run(self, *args, **kwargs):
        self.function(*self.args, **self.kwargs)
        self.finished.emit()


class Observe(QMainWindow):
    """
    The Observe class which implements observing scripts.

    This class is instantiated as the *observe* object.
    Scripts may be run from a text file using .observe() or executed within
    loaded a GUI using .start().
    """

    def __init__(self):

        super().__init__()

        self.debug = 0  #: True to NOT execute commands
        self.verbose = 1  #: True to print commands during run()
        self.number_cycles = 1  #: Number of times to run the script.
        self.move_telescope_during_readout = 0  #: True to move the telescope during camera readout
        self.increment_status = 0  #: True to increment status count if command in completed

        self.script_file = ""  #: filename of observing commands cript file
        self.out_file = ""  #: output file showing executed commands

        self.lines = []
        self.commands = []  # list of dictionaries for each command to be executed
        self.current_line = -1  # current line being executed

        self.current_filter = ""  # current filter

        self._abort_script = 0  #: internal abort flag to stop scipt
        self._abort_gui = 0  #: internal abort flag to stop GUI
        self._paused = 0  #: internal pause flag
        self._do_highlight = 0  #: internal highlight row flag

        self.et_scale = 1.0  #: exposure time scale factor

        # timer/tickers
        self._index = 0
        self.tickers = ["|", "/", "-", "\\"]

        self.data = []  # list of dictionaries for each command to be executed

        self.threadPool = []

        self.GuiMode = 1

    def initialize(self):
        """
        Initialize observe.
        """

        # setup GUI
        self._init_observe_gui()

        return

    def _init_observe_gui(self, parent=None):
        """
        Initialize GUI.
        """

        # QWidget.__init__(self, parent)
        self.parent = parent

        # QMainWindow()
        self.ui = Ui_observe()
        self.ui.setupUi(self)

        # connect buttons
        self.ui.pushButton_abort_script.released.connect(self.abort_script)
        self.ui.pushButton_run.released.connect(self.run_thread)
        self.ui.pushButton_selectscript.released.connect(self.select_script)
        self.ui.pushButton_editscript.released.connect(self.edit_script)
        self.ui.pushButton_loadscript.released.connect(self.load_script)
        self.ui.pushButton_pause_script.released.connect(self.pause_script)
        self.ui.pushButton_scale_et.released.connect(self.scale_exptime)

        # self.ui.tableWidget_script.resizeColumnsToContents()
        self.ui.tableWidget_script.setAlternatingRowColors(True)

        # event when table cells change
        self.ui.tableWidget_script.itemChanged.connect(self.cell_changed)

        # create and start a timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._watchdog)
        self.timer.start(500)

        # set defaults from parfile
        self.script_file = azcam.db.genpars.get_par(
            "observe", "script_file", "default", "", "observing_script.txt"
        )
        self.ui.plainTextEdit_filename.setPlainText(self.script_file)

        number_cycles = azcam.db.genpars.get_par("observe", "number_cycles", "default", "", 1)
        self.number_cycles = int(number_cycles)
        self.ui.spinBox_loops.setValue(self.number_cycles)

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

    def help(self):
        """
        Print help on scripting commands.
        """

        print("Observe class help...")
        print("")
        print('Always use double quotes (") when needed')
        print("")
        print("Comment lines start with # or !")
        print("")
        print("obs        ExposureTime imagetype Title NumberExposures Filter RA DEC Epoch")
        print("test       ExposureTime imagetype Title NumberExposures Filter RA DEC Epoch")
        print("")
        print("stepfocus  RelativeNumberSteps")
        print("steptel    RA_ArcSecs Dec_ArcSecs")
        print("movetel    RA Dec Epoch")
        print("movefilter FilterName")
        print("")
        print("delay      NumberSecs")
        print('print      hi there"')
        print('prompt     "press any key to continue..."')
        print("quit       quit script")
        print("")
        print("Script line examples:")
        print('obs 10.5 object "M31 field F" 1 u 00:36:00 40:30:00 2000.0 ')
        print('obs 2.3 dark "mike test dark" 2 u')
        print("stepfocus 50")
        print("delay 3")
        print("stepfocus -50")
        print("steptel 12.34 12.34")
        print("# this is a comment line")
        print("! this is also a comment line")
        print("movetel 112940.40 +310030.0 2000.0")
        print("")

        return

    def read_file(self, script_file="prompt"):
        """
        Read an observing script file.

        :param script_file: full path name of script file. If 'prompt', then ask for filename.
        :return: None
        """

        if self.GuiMode:
            self.script_file = str(self.ui.plainTextEdit_filename.toPlainText())
        else:
            self.script_file = script_file

        # make output filename by appending _out to base filename
        base, ext = os.path.splitext(self.script_file)
        self.out_file = base + "_out" + ext

        # read file
        with open(self.script_file, "r") as sfile:
            all_lines = sfile.readlines()

        # save all lines
        self.lines = []
        self.commands = []  # list of dictionaries, one for each line
        for line in all_lines:
            if line == "\n":
                continue
            line = line.strip()
            self.lines.append(line)

        return

    def parse(self):
        """
        Parse current line set into self.commands dictionary.
        The script file must have already been read using read_file().

        :return: None
        """

        for linenumber, line in enumerate(self.lines):

            expose_flag = 0
            movetel_flag = 0
            steptel_flag = 0
            movefilter_flag = 0
            movefocus_flag = 0
            wave = ""
            focus = ""
            ra = ""
            dec = ""
            raNext = ""
            decNext = ""
            epoch = ""
            exptime = 0.0
            imagetype = ""
            arg = ""
            title = ""
            numexposures = 0
            status = 0

            tokens = azcam.utils.parse(line)

            # comment line, special case
            if line.startswith("#") or line.startswith("!") or line.startswith("comment"):
                cmd = "comment"
                arg = line[1:].strip()

            # if the first token is a number, it is a status flag - save and remove from parsing
            elif tokens[0].isdigit():
                status = int(tokens[0])
                line = line.lstrip(tokens[0]).strip()
                tokens = tokens[1:]  # reset tokens to not include status
                cmd = tokens[0].lower()
            else:
                status = -1  # indicates no status value
                cmd = tokens[0].lower()

            # comment
            if cmd == "comment":
                pass

            # prompt, use quotes for string
            elif cmd == "prompt":
                arg = tokens[1]

            # print
            elif cmd == "print":
                arg = tokens[1]

            elif cmd == "prompt":
                arg = tokens[1]

            # issue a raw server which should be in single quotes
            elif cmd == "azcam":
                arg = tokens[1]

            # take a normal observation
            elif cmd == "obs":
                # obs 10.5 object "M31 field F" 1 U 00:36:00 40:30:00 2000.0
                exptime = float(tokens[1])
                imagetype = tokens[2]
                title = tokens[3].strip('"')  # remove double quotes
                numexposures = int(tokens[4])
                expose_flag = 1
                if len(tokens) > 5:
                    wave = tokens[5].strip('"')
                    movefilter_flag = 1
                if len(tokens) > 6:
                    ra = tokens[6]
                    dec = tokens[7]
                    if len(tokens) > 8:
                        epoch = tokens[8]
                    else:
                        epoch = 2000.0
                    movetel_flag = 1
                else:
                    ra = ""
                    dec = ""
                    epoch = ""
                    movetel_flag = 0

            # take test images
            elif cmd == "test":
                # test 10.5 object "M31 field F" 1 U 00:36:00 40:30:00 2000.0
                exptime = float(tokens[1])
                imagetype = tokens[2]
                title = tokens[3].strip('"')
                numexposures = int(tokens[4])
                expose_flag = 1
                if len(tokens) > 5:
                    wave = tokens[5].strip('"')
                    movefilter_flag = 1
                if len(tokens) > 6:
                    ra = tokens[6]
                    dec = tokens[7]
                    if len(tokens) > 8:
                        epoch = tokens[8]
                    else:
                        epoch = 2000.0
                    movetel_flag = 1
                else:
                    ra = ""
                    dec = ""
                    epoch = ""
                    movetel_flag = 0

            # move focus position in relative steps from current position
            elif cmd == "stepfocus":
                # stepfocus RelativeSteps
                focus = float(tokens[1])
                # reply=step_focus(focus)
                movefocus_flag = 1

            # move filter
            elif cmd == "movefilter":
                # movefilter FilterName
                wave = tokens[1]
                movefilter_flag = 1

            # move telescope to absolute RA DEC EPOCH
            elif cmd == "movetel":
                # movetel ra dec
                ra = tokens[1]
                dec = tokens[2]
                epoch = tokens[3]
                movetel_flag = 1

            # slew telescope to absolute RA DEC EPOCH
            elif cmd == "slewtel":
                # slewtel ra dec
                ra = tokens[1]
                dec = tokens[2]
                epoch = tokens[3]
                movetel_flag = 1

            # move telescope relative RA DEC
            elif cmd == "steptel":
                # steptel raoffset decoffset
                raoffset = tokens[1]
                decoffset = tokens[2]
                ra = raoffset
                dec = decoffset
                movetel_flag = 1

            # delay N seconds
            elif cmd == "delay":
                delay = float(tokens[1])
                arg = delay

            # quit script
            elif cmd == "quit":
                pass

            else:
                azcam.log("command not recognized on line %03d: %s" % (linenumber, cmd))

            # get next RA and DEC if next line is obs command
            raNext = ""
            decNext = ""
            epochNext = ""
            if linenumber == len(self.lines) - 1:  # last line
                pass
            else:
                lineNext = self.lines[linenumber + 1]
                tokensNext = azcam.utils.parse(lineNext)
                lentokNext = len(tokensNext)
                if lentokNext != 0:
                    cmdNext = tokensNext[0].lower()
                    if cmdNext == "obs" and lentokNext > 6:
                        raNext = tokensNext[6]
                        decNext = tokensNext[7]
                        epochNext = tokensNext[8]
                    else:
                        pass

            data1 = {}
            data1["line"] = line
            data1["cmdnumber"] = linenumber
            data1["status"] = status
            data1["command"] = cmd
            data1["argument"] = arg
            data1["exptime"] = exptime
            data1["type"] = imagetype
            data1["title"] = title
            data1["numexp"] = numexposures
            data1["filter"] = wave
            data1["focus"] = focus
            data1["ra"] = ra
            data1["dec"] = dec
            data1["ra_next"] = raNext
            data1["dec_next"] = decNext
            data1["epoch"] = epoch
            data1["expose_flag"] = expose_flag
            data1["movetel_flag"] = movetel_flag
            data1["steptel_flag"] = steptel_flag
            data1["movefilter_flag"] = movefilter_flag
            data1["movefocus_flag"] = movefocus_flag
            self.commands.append(data1)

        return

    def update_cell(self, command_number, parameter="", value=""):
        """
        Update one parameter of an existing command.

        :param command_number: Number of command to be updated. If -1, return list of possible arguments.
        :param parameter: Paramater name to be updated.
        :param value: New value of parameter.
        :return: None
        """

        if command_number == -1:
            pars = []
            pars.append("line")
            pars.append("cmdnumber")
            pars.append("status")
            pars.append("command")
            pars.append("argument")
            pars.append("exptime")
            pars.append("type")
            pars.append("title")
            pars.append("numexp")
            pars.append("filter")
            pars.append("focus")
            pars.append("ra")
            pars.append("dec")
            pars.append("ra_next")
            pars.append("dec_next")
            pars.append("epoch")
            pars.append("expose_flag")
            pars.append("movetel_flag")
            pars.append("steptel_flag")
            pars.append("movefilter_flag")
            pars.append("movefocus_flag")

            return pars

        self.commands[command_number][parameter.lower()] = value

        self.update_table()

        return

    def update_line(self, line_number, line):
        """
        Add or update a script line.

        :param line_number: Number of line to be updated or -1 to add at the end of the line buffer.
        :param line: New string (line). If line is "", then line_number is deleted.
        :return: None
        """

        if line_number == -1:
            self.lines.append(line)
            return

        if line == "":
            if line_number < len(self.lines) - 1:
                self.lines.pop(line_number)
                return

        self.lines[line_number] = line

        return

    def scale_exptime(self):
        """
        Scale the current exposure times.
        """

        self.status("Working...")

        self.et_scale = float(self.ui.doubleSpinBox_ExpTimeScale.value())

        for cmdnum, cmd in enumerate(self.commands):
            old = float(cmd["exptime"])
            new = old * self.et_scale
            self.update_cell(cmdnum, "exptime", new)

        self.status("")

        return

    def log(self, message):
        """
        Log a message.
        :param message: string to be logged.
        :return: None
        """

        azcam.log(message)

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

        # observe() is only call without the GUI
        self.GuiMode = 0

        # get inputs
        if script_file == "prompt":
            script_file = azcam.db.genpars.get_par(
                "observe", "script_file", "default", "Enter script file name", ""
            )
            script_file = azcam.utils.file_browser(
                script_file, [("script files", ("*.txt"))], Label="Select script file"
            )
            if script_file is not None and script_file != "":
                script_file = script_file[0]
                self.script_file = script_file
                azcam.db.genpars.set_par("observe", "script_file", script_file)
            else:
                return "ERROR selecting script file"

        if number_cycles == "prompt":
            self.number_cycles = azcam.db.genpars.get_par(
                "observe",
                "number_cycles",
                "prompt",
                "Enter number of cycles to run script",
                number_cycles,
            )
        else:
            self.number_cycles = number_cycles  # use value specified
        self.number_cycles = int(self.number_cycles)

        # read and parse the script
        self.read_file(script_file)
        self.parse()

        # execute the commands
        self.run()

        return

    def run(self):
        """
        Execute the commands in the script command dictionary.

        :return: None
        """

        self._abort_script = 0

        # save pars to be changed
        impars = {}
        azcam.console.api.save_imagepars(impars)

        # log start info
        s = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log("Observing script started: %s" % s)

        # begin execution loop
        offsets = []
        for loop in range(self.number_cycles):

            if self.number_cycles > 1:
                self.log("*** Script cycle %d of %d ***" % (loop + 1, self.number_cycles))

            # open output file
            with open(self.out_file, "w") as ofile:
                if not ofile:
                    azcam.console.api.restore_imagepars(impars)
                    self.log("could not open script output file %s" % self.out_file)
                    azcam.AzcamWarning("could not open script output file")
                    return

                for linenumber, command in enumerate(self.commands):

                    stop = 0

                    line = command["line"]
                    status = command["status"]

                    self.log("Command %03d/%03d: %s" % (linenumber, len(self.commands), line))

                    # execute the command
                    reply = self.execute_command(linenumber)

                    keyhit = azcam.utils.check_keyboard(0)
                    print("key", keyhit)
                    if keyhit == "q":
                        reply = "QUIT"

                    if reply == "STOP":
                        self.log("STOP after line %d" % linenumber)
                        stop = 1
                    elif reply == "QUIT":
                        stop = 1
                        self.log("QUIT after line %d" % linenumber)
                    else:
                        self.log("Reply %03d: %s" % (linenumber, reply))

                    # update output file and status
                    if command["command"] in [
                        "comment",
                        "print",
                        "delay",
                        "prompt",
                        "quit",
                    ]:  # no status
                        ofile.write("%s " % line + "\n")
                    elif self.increment_status:  # add status if needed
                        if status == -1:
                            status = 0
                        if stop:
                            ofile.write("%s " % status + line + "\n")
                        else:
                            ofile.write("%s " % (status + 1) + line + "\n")
                    else:
                        if stop:  # don't inc on stop
                            ofile.write("%s " % line + "\n")
                        else:
                            if status == -1:
                                ofile.write("%s " % line + "\n")
                            else:
                                ofile.write("%s " % (status) + line + "\n")

                    if stop or self._abort_script:
                        break

                    # check for pause
                    if self.GuiMode:
                        while self._paused:
                            self.wait4highlight()
                            time.sleep(1)

                # write any remaining lines to output file
                for i in range(linenumber + 1, len(self.commands)):
                    line = self.commands[i]["line"]
                    line = line.strip()
                    ofile.write(line + "\n")

        # finish
        azcam.console.api.restore_imagepars(impars)
        self._abort_script = 0  # clear abort status

        return

    def execute_command(self, linenumber):
        """
        Execute one command.

        :param linenumber: Line number to execute, from command buffer.
        """

        # wait for highlighting of current row
        if self.GuiMode:
            self.current_line = linenumber
            self.wait4highlight()

        command = self.commands[linenumber]
        if self.debug:
            time.sleep(0.5)
            return "OK"

        reply = "OK"

        expose_flag = 0
        movetel_flag = 0
        steptel_flag = 0
        movefilter_flag = 0
        movefocus_flag = 0
        wave = ""
        ra = ""
        dec = ""
        epoch = ""
        exptime = ""
        imagetype = ""
        arg = ""
        title = ""
        numexposures = ""
        status = 0

        # get command and all parameters
        line = command["line"]
        cmd = command["command"]

        status = command["status"]
        arg = command["argument"]
        exptime = command["exptime"]
        imagetype = command["type"]
        title = command["title"]
        numexposures = command["numexp"]
        wave = command["filter"]
        ra = command["ra"]
        dec = command["dec"]
        raNext = command["ra_next"]
        decNext = command["dec_next"]
        epoch = command["epoch"]
        epochNext = command["epoch"]  # debug
        expose_flag = command["expose_flag"]
        movetel_flag = command["movetel_flag"]
        steptel_flag = command["steptel_flag"]
        movefilter_flag = command["movefilter_flag"]
        movefocus_flag = command["movefocus_flag"]

        exptime = float(exptime)
        numexposures = int(numexposures)
        expose_flag = int(expose_flag)
        movetel_flag = int(movetel_flag)
        steptel_flag = int(steptel_flag)
        movefilter_flag = int(movefilter_flag)
        movefocus_flag = int(movefocus_flag)

        # perform some immediate actions

        # comment
        if cmd == "comment":  # do nothing
            return "OK"

        elif cmd == "obs":
            pass

        elif cmd == "test":
            pass

        elif cmd == "offset":
            pass

        elif cmd == "stepfocus":
            reply = azcam.console.api.step_focus(arg)

        elif cmd == "movefilter":
            pass

        elif cmd == "movetel":
            pass

        # display message and then change command, for now
        elif cmd == "slewtel":
            cmd = "movetel"
            self.log("Enable slew for next telescope motion")
            reply = azcam.utils.prompt("Waiting...")
            return "OK"

        elif cmd == "steptel":
            self.log("offsetting telescope in arcsecs - RA: %s, DEC: %s" % (raoffset, decoffset))
            try:
                reply = azcam.console.api.rcommand(f"telescope.offset {raoffset} {decoffset}")
                return "OK"
            except azcam.AzcamError as e:
                return f"ERROR {e}"

        elif cmd == "delay":
            time.sleep(float(arg))
            return "OK"

        elif cmd == "azcam":
            try:
                reply = azcam.console.api.rcommand(arg)
                return reply
            except azcam.AzcamError as e:
                return f"ERROR {e}"

        elif cmd == "print":
            self.log(arg)
            return "OK"

        elif cmd == "prompt":
            self.log("prompt not available: %s" % arg)
            return "OK"

        elif cmd == "quit":
            self.log("quitting...")
            return "QUIT"

        else:
            self.log("script command %s not recognized" % cmd)

        # perform actions based on flags

        # move focus
        if movefocus_flag:
            self.log("Moving to focus: %s" % focus)
            if not self.DummyMode:
                reply = azcam.console.api.set_focus(focus)
                # reply, stop = check_exit(reply, 1)
                stop = self._abort_gui
                if stop:
                    return "STOP"
                reply = azcam.console.api.get_focus()
                self.log("Focus reply:: %s" % repr(reply))
                # reply, stop = check_exit(reply, 1)
                stop = self._abort_gui
                if stop:
                    return "STOP"

        # set filter
        if movefilter_flag:
            if wave != self.current_filter:
                self.log("Moving to filter: %s" % wave)
                if not self.debug:
                    azcam.console.api.set_filter(wave)
                    reply = azcam.console.api.get_filter()
                    self.current_filter = reply
            else:
                self.log("Filter %s already in beam" % self.current_filter)

        # move telescope to RA and DEC
        if movetel_flag:
            self.log("Moving telescope now to RA: %s, DEC: %s" % (ra, dec))
            if not self.debug:
                try:
                    reply = azcam.console.api.rcommand(f"telescope.move {ra} {dec} {epoch}")
                except azcam.AzcamError as e:
                    return f"ERROR {e}"

        # make exposure
        if expose_flag:
            for i in range(numexposures):
                if steptel_flag:
                    self.log(
                        "Offsetting telescope in RA: %s, DEC: %s"
                        % (offsets[i * 2], offsets[i * 2 + 1])
                    )
                    if not self.debug:
                        reply = TelescopeOffset(offsets[i * 2], offsets[i * 2 + 1])
                        # reply, stop = check_exit(reply, 1)
                        stop = self._abort_gui
                        if stop:
                            return "STOP"

                if cmd != "test":
                    azcam.console.api.set_par("imagetest", 0)
                else:
                    azcam.console.api.set_par("imagetest", 1)
                filename = azcam.console.api.get_image_filename()

                if cmd == "test":
                    self.log(
                        "test %s: %d of %d: %.3f sec: %s"
                        % (imagetype, i + 1, numexposures, exptime, filename)
                    )
                else:
                    self.log(
                        "%s: %d of %d: %.3f sec: %s"
                        % (imagetype, i + 1, numexposures, exptime, filename)
                    )

                if self.move_telescope_during_readout and (raNext != ""):

                    if i == numexposures - 1:  # Apr15
                        doMove = 1
                    else:
                        doMove = 0

                    if 1:
                        # if not self.debug:
                        reply = azcam.console.api.expose1(
                            exptime, imagetype, title
                        )  # immediate return
                        time.sleep(2)  # wait for Expose process to start
                        cycle = 1
                        while 1:
                            flag = azcam.console.api.get_par("ExposureFlag")
                            if flag is None:
                                self.log("Could not get exposure status, quitting...")
                                stop = 1
                                return "STOP"
                            if (
                                flag == azcam.db.exposureflags["EXPOSING"]
                                or flag == azcam.db.exposureflags["SETUP"]
                            ):
                                flagstring = "Exposing"
                            elif flag == azcam.db.exposureflags["READOUT"]:
                                flagstring = "Reading"
                                if doMove:
                                    check_header = 1
                                    while check_header:
                                        header_updating = int(
                                            azcam.console.api.get_par("exposureupdatingheader")
                                        )
                                        if header_updating:
                                            self.log("Waiting for header to finish updating...")
                                            time.sleep(0.5)
                                        else:
                                            check_header = 0
                                    self.log(
                                        "Moving telescope to next field - RA: %s, DEC: %s"
                                        % (raNext, decNext)
                                    )
                                    try:
                                        reply = azcam.console.api.rcommand(
                                            "telescope.move_start %s %s %s"
                                            % (raNext, decNext, epochNext)
                                        )
                                    except azcam.AzcamError as e:
                                        return f"ERROR {e}"
                                    doMove = 0
                            elif flag == azcam.db.exposureflags["WRITING"]:
                                flagstring = "Writing"
                            elif flag == azcam.db.exposureflags["NONE"]:
                                flagstring = "Finished"
                                break
                            # self.log('Checking Exposure Status (%03d): %10s\r' % (cycle,flagstring))
                            time.sleep(0.1)
                            cycle += 1
                else:
                    if not self.debug:
                        azcam.console.api.expose(exptime, imagetype, title)

                # reply, stop = check_exit(reply)
                stop = self._abort_gui
                if stop:
                    return "STOP"

        return "OK"

    def _watchdog(self):
        """
        Update counter field indicating GUI in running and highlight current table row.
        """

        if not self.GuiMode:
            return

        # check abort
        if self._abort_gui:
            self.status("Aborting GUI")
            print("Aborting observe GUI")
            return

        if self._paused:
            self.status("Script PAUSED")

        # ticker
        x = self.tickers[self._index]  # list of ticker chars
        self.ui.label_counter.setText(x)
        self.ui.label_counter.repaint()
        self._index += 1
        if self._index > len(self.tickers) - 1:
            self._index = 0

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

        return

    def run_thread(self):
        """
        Start the script execution thread so that _abort_script may be used.
        """

        self.GuiMode = 1

        self.status("Running...")
        self.number_cycles = self.ui.spinBox_loops.value()  # set number of cycles to run script

        my_thread = QtCore.QThread()
        my_thread.start()

        # This causes my_worker.run() to eventually execute in my_thread:
        my_worker = GenericWorker(self.run)
        my_worker.moveToThread(my_thread)
        my_worker.start.emit("hello")
        my_worker.finished.connect(self.run_finished)

        self.threadPool.append(my_thread)
        self.my_worker = my_worker

    def run_finished(self):
        """
        Called when the run thread is finished.
        """

        self.current_line = -1
        self.highlight_row(len(self.commands) - 1, 0)
        self.status("Run finished")  # clear status box

        # save pars
        # azcam.utils.update_pars(1, "observe")
        azcam.db.genpars.parfile_write()

        return

    def select_script(self):
        """
        Select a script file using dialog box.
        """

        filename = str(self.ui.plainTextEdit_filename.toPlainText())
        folder = os.path.dirname(filename)
        filename = QFileDialog.getOpenFileName(
            self.parent, "Select script filename", folder, "Scripts (*.txt)"
        )
        self.ui.plainTextEdit_filename.setPlainText(filename[0])
        filename = str(filename[0])
        azcam.db.genpars.set_par("observe", "script_file", filename)

        return

    def edit_script(self):
        """
        Edit the select a script file.
        """

        filename = str(self.ui.plainTextEdit_filename.toPlainText())

        os.startfile(filename)  # opens notepad for .txt files

        return

    def load_script(self):
        """
        Read script file and load into table.
        """

        # open observing script text file
        filename = str(self.ui.plainTextEdit_filename.toPlainText())
        with open(filename, "r") as ofile:
            if not ofile:
                self.ui.label_status.setText("could not open script")
                return

        self.read_file(filename)
        self.out_file = self.out_file
        self.parse()

        # fill in table
        self.update_table()

        return

    def cell_changed(self, item):
        """
        Called when a table cell is changed.
        """

        row = item.row()
        col = item.column()
        newvalue = item.text()

        colnum = self.column_number[col]

        self.commands[row][colnum] = newvalue

        return

    def update_table(self):
        """
        Update entire GUI table with current values of .commands.
        """

        # fill in table
        self.ui.tableWidget_script.setRowCount(len(self.commands))
        for row, data1 in enumerate(self.commands):
            col = 0
            for key in self.column_order:
                newitem = QTableWidgetItem(str(data1[key]))
                self.ui.tableWidget_script.setItem(row, col, newitem)
                col += 1

        self.ui.tableWidget_script.resizeColumnsToContents()
        self.ui.tableWidget_script.resizeRowsToContents()
        height = min(300, self.ui.tableWidget_script.verticalHeader().length() + 60)
        self.ui.tableWidget_script.setFixedSize(
            self.ui.tableWidget_script.horizontalHeader().length() + 20, height
        )

        return

    def highlight_row(self, row_number, flag):
        """
        Highlight or unhighlight a row of the GUI table during execution.
        Highlighting cannot occur in thread.
        """

        numcols = self.ui.tableWidget_script.columnCount()

        # higlight row being executed
        if flag == 0:
            # uncolor row
            for col in range(numcols):
                item = self.ui.tableWidget_script.item(row_number, col)
                item.setBackground(QtGui.QColor(QtCore.Qt.transparent))
                self.ui.tableWidget_script.repaint()

        elif flag == 1:
            # green
            for col in range(numcols):
                item = self.ui.tableWidget_script.item(row_number, col)
                item.setBackground(QtGui.QColor(0, 255, 0))
                self.ui.tableWidget_script.repaint()

        elif flag == 2:
            # alt color for pause
            for col in range(numcols):
                item = self.ui.tableWidget_script.item(row_number, col)
                item.setBackground(QtGui.QColor(255, 255, 153))
                self.ui.tableWidget_script.repaint()

        elif flag == 3:
            # alt color for abort
            for col in range(numcols):
                item = self.ui.tableWidget_script.item(row_number, col)
                item.setBackground(QtGui.QColor(255, 100, 100))
                self.ui.tableWidget_script.repaint()

        return

    def wait4highlight(self):
        """
        Wait for row to highlight.
        """

        self._do_highlight = 1
        if self._do_highlight:
            while self._do_highlight:
                time.sleep(0.1)

        return

    def status(self, message):
        """
        Display text in status field.
        """

        self.ui.label_status.setText(str(message))
        self.ui.label_status.repaint()

        return

    def abort_script(self):
        """
        Abort a running script as soon as possible.
        """

        self._abort_script = 1
        self.status("Abort detected")

        # self.wait4highlight()
        self._do_highlight = 1

        return

    def pause_script(self):
        """
        Pause a running script as soon as possible.
        """

        self._paused = not self._paused
        if self._paused:
            s = "Pause detected"
        else:
            s = "Running..."
        self.status(s)

        # self.wait4highlight()
        self._do_highlight = 1

        return

    def start(self):
        """
        Show the GUI.
        """

        self.initialize()

        # show GUI
        self.show()
        self.status("ready...")

        # set window location
        self.move(50, 50)

        return

    def stop(self):
        """
        Stop the GUI for the Observe class.
        """

        self._abort_gui = 1

        return


# ****************************************************************
# create Qt app
# ****************************************************************
if azcam.db.get("atapp") is None:
    app = QtCore.QCoreApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    azcam.db.qtapp = app
