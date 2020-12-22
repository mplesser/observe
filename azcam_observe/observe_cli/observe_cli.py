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

import azcam
from azcam_observe.observe import Observe


class ObserveCli(Observe):
    """
    The Observe class which implements observing scripts.

    This class is instantiated as the *observe* object.
    Scripts are run using observe.observe().
    """

    def __init__(self):

        super().__init__()

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
        azcam.utils.save_imagepars(impars)

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
                    azcam.utils.restore_imagepars(impars)
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
                    if keyhit == "q":
                        reply = "QUIT"
                        stop = 1

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
        azcam.utils.restore_imagepars(impars)
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
            reply = azcam.api.step_focus(arg)

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
                reply = azcam.api.server.rcommand(f"telescope.offset {raoffset} {decoffset}")
                return "OK"
            except azcam.AzcamError as e:
                return f"ERROR {e}"

        elif cmd == "delay":
            time.sleep(float(arg))
            return "OK"

        elif cmd == "azcam":
            try:
                reply = azcam.api.server.rcommand(arg)
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
                reply = self._set_focus(focus)
                # reply, stop = check_exit(reply, 1)
                stop = self._abort_gui
                if stop:
                    return "STOP"
                reply = self._get_focus()
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
                    azcam.api.instrument.set_filter(wave)
                    reply = azcam.api.instrument.get_filter()
                    self.current_filter = reply
            else:
                self.log("Filter %s already in beam" % self.current_filter)

        # move telescope to RA and DEC
        if movetel_flag:
            self.log("Moving telescope now to RA: %s, DEC: %s" % (ra, dec))
            if not self.debug:
                try:
                    reply = azcam.api.server.rcommand(f"telescope.move {ra} {dec} {epoch}")
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
                    azcam.api.exposure.set_par("imagetest", 0)
                else:
                    azcam.api.exposure.set_par("imagetest", 1)
                filename = azcam.api.exposure.get_image_filename()

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
                        reply = azcam.api.exposure.expose1(
                            exptime, imagetype, title
                        )  # immediate return
                        time.sleep(2)  # wait for Expose process to start
                        cycle = 1
                        while 1:
                            flag = azcam.api.exposure.get_par("ExposureFlag")
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
                                            azcam.api.exposure.get_par("exposureupdatingheader")
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
                                        reply = azcam.api.server.rcommand(
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
                        azcam.api.exposure.expose(exptime, imagetype, title)

                # reply, stop = check_exit(reply)
                stop = self._abort_gui
                if stop:
                    return "STOP"

                keyhit = azcam.utils.check_keyboard(0)
                if keyhit == "q":
                    return "QUIT"

        return "OK"
