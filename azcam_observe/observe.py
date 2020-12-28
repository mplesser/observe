"""
Contains the Observe class for Qt and CLI usage.
"""

from .observe_qt.observe_qt import ObserveQt
from .observe_cli.observe_cli import ObserveCli


class Observe(ObserveQt, ObserveCli):
    """
    The common Observe class for both Qt and CLI usage.
    """

    def __init__(self):

        ObserveQt.__init__(self)
        ObserveCli.__init__(self)
