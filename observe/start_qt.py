from PySide2.QtWidgets import QApplication

import azcam


def start_qt():

    if azcam.db.qtapp is None:
        azcam.db.qtapp = QApplication([])

    return
